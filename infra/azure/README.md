# SaaS Job API on Azure

Bicep for the dev environment in subscription **CertVision360-DEV**, region **Australia East**. It deploys into the existing resource groups `rg-cv360-<area>-dev`.

```
Internet ── HTTPS ──> Container Apps ingress (public)
gateways, admins       │
                       ▼
  vnet-cv360-dev 10.40.0.0/16
  ├─ snet-aca  10.40.0.0/23   cae-cv360-dev: ca-cv360-api-dev (API)
  │                                          caj-cv360-migrate-dev (alembic job)
  ├─ snet-psql 10.40.2.0/24   psql-cv360-dev (PostgreSQL 17, no public endpoint, TLS)
  └─ snet-pe   10.40.3.0/24   private endpoint of kv-cv360-dev (app secrets)
```

| Resource group | What | Module |
|---|---|---|
| rg-cv360-network-dev | VNet, 3 subnets, private DNS zones (postgres, vaultcore) | `modules/network.bicep` |
| rg-cv360-monitor-dev | Log Analytics `log-cv360-dev` (30 days, 1 GB/day cap) | `modules/monitor.bicep` |
| rg-cv360-data-dev | PostgreSQL Flexible Server `psql-cv360-dev`, database `saas` | `modules/data.bicep` |
| rg-cv360-security-dev | identity `id-cv360-api-dev`, `database-url` secret, vault private endpoint | `modules/security.bicep` |
| rg-cv360-app-dev | Container Apps environment, API app, migration job, AcrPull for the identity | `modules/app.bicep` |

## Secrets

The app's settings come from Key Vault references, which the container app resolves with its managed identity. No secret appears in the templates, the parameters, or the app configuration.

| Key Vault secret | Environment variable | Written by |
|---|---|---|
| `postgres-admin-password` | (deployment only) | `bootstrap-secrets.sh` |
| `database-url` | `SAAS_JOB_API_DATABASE_URL` | the deployment (`...?sslmode=require`) |
| `admin-token` | `SAAS_JOB_API_ADMIN_TOKEN` | `bootstrap-secrets.sh` |
| `jwt-secret` | `SAAS_JOB_API_JWT_SECRET` | `bootstrap-secrets.sh` |
| `admin-password` | `SAAS_JOB_API_BOOTSTRAP_ADMIN_PASSWORD` (user `platform-admin`) | `bootstrap-secrets.sh` |
| `gateway-tokens-json` | `SAAS_JOB_API_GATEWAY_TOKENS_JSON` | `bootstrap-secrets.sh` (`{}`), then you |
| `gateway-tenants-json` | `SAAS_JOB_API_GATEWAY_TENANTS_JSON` | `bootstrap-secrets.sh` (`{}`), then you |

## First deployment

Run these from the repository root with the Azure CLI signed in (`az login`).

1. **Secrets** (you run this; it prints no values):
   ```bash
   bash infra/azure/bootstrap-secrets.sh
   ```
2. **Image**: build it in the registry and note the digest.
   ```bash
   az acr build -r acrcv360dev -t saas-job-api:<version> --platform linux/amd64 .
   ```
3. **Preview, then deploy:**
   ```bash
   export API_IMAGE=acrcv360dev.azurecr.io/saas-job-api@sha256:<digest>
   az deployment sub what-if -l australiaeast -f infra/azure/main.bicep -p infra/azure/dev.bicepparam
   az deployment sub create  -l australiaeast -f infra/azure/main.bicep -p infra/azure/dev.bicepparam
   ```
4. **Migrate** the database, then check that the API responds:
   ```bash
   az containerapp job start -g rg-cv360-app-dev -n caj-cv360-migrate-dev
   curl -fsS https://<apiUrl output>/healthz
   ```

On a first deployment the API starts before the tables exist, so it logs `UndefinedTableError` from the scheduler until the migration job finishes (about a minute); that is expected.

For later releases, repeat steps 2–4: new image digest, deploy, migrate. Run migrations before the new API revision takes traffic.

## Cost (dev, approximate, USD/month)

| Item | ~Cost |
|---|---|
| PostgreSQL Burstable B1ms + 32 GB storage | 20 |
| Container Apps: 1 replica (0.5 vCPU, 1 GiB) always on, after the free grant | 25 |
| Key Vault private endpoint | 8 |
| Log Analytics (capped at 1 GB/day) | 2–5 |
| Private DNS zones | 1 |
| **Total** | **≈ 55–60** |

The subscription's budget alert (`cv360-dev-monthly`, $30) has to be raised before deploying.

## Production differences

- PostgreSQL General Purpose with zone-redundant HA, geo-redundant backups, and Entra ID authentication instead of a password.
- `kv-cv360-dev` (Standard) is replaced by a vault with purge protection and public network access **disabled**. Here it stays enabled so an operator can manage secrets from a laptop.
- ACR Premium, so the registry gets a private endpoint and the gateways' pull path can be restricted.
- A custom domain with a managed certificate on the API, plus front-door/WAF if needed.
- Gateways on mTLS registration instead of bearer tokens in `gateway-tokens-json`.
