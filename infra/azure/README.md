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

## Cost (dev, measured, AUD/month)

Measured from Cost Management in November 2026 (full days, billing currency AUD):

| Item | AUD/day | ~AUD/month | Pausable |
|---|---|---|---|
| Signing keys: 7 Premium HSM EC keys in the three TUF vaults, billed per key per month, used or not | – | 49.70 | no |
| PostgreSQL B1ms compute (+ storage ~0.10/day) | 1.10 | 33 | compute only |
| Container Apps environment load balancer + public IP (VNet integration) | 0.85 | 26 | no |
| API, 1 replica always on | 0.74 | 22 | yes |
| Key Vault private endpoint | 0.51 | 15.50 | no |
| Container Registry Basic | 0.24 | 7.30 | no |
| Private DNS zones, Log Analytics | 0.05 | 1.50 | no |
| **Total** | | **≈ 155** | |

Paused (`power.sh pause`) the hosting drops by about AUD 1.75/day, to about
AUD 53/month plus the signing keys. The keys are the largest single item;
dev could use software-protected keys instead (no monthly fee) at the cost
of a TUF root-key rotation, see the signing-ceremony document.

## Pausing when not testing

```bash
bash infra/azure/power.sh status   # API replicas, database state, month-to-date cost
bash infra/azure/power.sh pause    # API to 0 replicas, PostgreSQL stopped
bash infra/azure/power.sh resume   # PostgreSQL started, API to 1 replica, health check
```

Before pausing, switch the lab gateway away (`sudo cv-use-saas lab`) or shut
its VM down. While paused, schedules do not fire; on resume each overdue
schedule fires once and then keeps its interval. Azure restarts a stopped
PostgreSQL server by itself after 7 days, and a deployment needs the server
running, so `resume` first.

## Tearing down between test periods

For breaks longer than a week, delete what is billed by the hour and rebuild later:

```bash
bash infra/azure/teardown.sh                          # asks you to type "teardown"
bash deploy/test-lab/azure/rebuild-lab.sh             # CDE repo: ~30 min, back to a connected lab
```

Teardown deletes the API, its jobs, the Container Apps environment (and its load
balancer) and the Key Vault private endpoint. It **stops** the PostgreSQL
server instead of deleting it, keeping all data (storage only, ~AUD 3/month):
on 2026-11-18 Azure refused to create a new Burstable server (B1ms and B2s,
SkuNotAvailable) in australiaeast for this subscription. Azure restarts a
stopped server after 7 days; run `teardown.sh` again then (it is safe to rerun)
to stop it again. `rebuild.sh` starts it before deploying. The registry,
Key Vaults, keys, secrets, identities, network and Log Analytics stay. The API image in use is tagged `saas-job-api:deployed-dev`
and `rebuild.sh` redeploys it. The API URL changes on every rebuild; the lab
scripts look it up from Azure and `rebuild-lab.sh` updates GitHub and the gateway.

## Schedules

The scheduler skips a run while that schedule's previous job is still queued,
or running for less than `SAAS_JOB_API_SCHEDULE_RUNNING_JOB_TIMEOUT_SECONDS`
(default 6 h; older running jobs count as stuck). Edit a schedule with
`PATCH /admin/v1/tenants/{tenantId}/schedules/{scheduleId}` and any of
`intervalSeconds` (minimum 300), `enabled` (false pauses it), `nextRunAt`.

## Production differences

- PostgreSQL General Purpose with zone-redundant HA, geo-redundant backups, and Entra ID authentication instead of a password.
- `kv-cv360-dev` (Standard) is replaced by a vault with purge protection and public network access **disabled**. Here it stays enabled so an operator can manage secrets from a laptop.
- ACR Premium, so the registry gets a private endpoint and the gateways' pull path can be restricted.
- A custom domain with a managed certificate on the API, plus front-door/WAF if needed.
- Gateways on mTLS registration instead of bearer tokens in `gateway-tokens-json`.

## Querying the database (read-only)

PostgreSQL has no public endpoint. To look at the data, run a query inside Azure:

```bash
bash infra/azure/sql.sh "SELECT target_id, subject, valid_to FROM certificate_records ORDER BY received_at DESC LIMIT 20"
```

The job `caj-cv360-sql-dev` runs it with `psql` in the private network as the role
`cv_readonly`: SELECT only, read-only transactions, and no access to tables that hold
token or password hashes. Each run gives the role a fresh random password that is
valid for 15 minutes and never output; the query never runs as the admin. The result
is read back from Log Analytics, so a query takes 1–3 minutes.

Useful tables: `jobs` (state, `reserved_by`, tenant/target), `job_results`
(record count per job), `certificate_records` (one row per certificate found).
