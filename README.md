# saas-job-api

Reference implementation of the "SaaS Job API" described in
`../docs/Gateway_VM_Job_Poller_Python_Technical_Design_v1.0.docx` §9 — the
server the Gateway VM Job Poller (in the parent repo) polls. This is a
single-tenant, in-memory test double for exercising and verifying the poller
client, not a production SaaS platform.

This is an independent git repository, nested inside the parent repo's
working tree purely for co-location convenience. It has no dependency on the
parent package other than the opt-in end-to-end test described below.

## Run it

```bash
pip install -e ".[dev]"
python scripts/run_dev.py
```

Default dev bearer token: `dev-gateway-token` (bound to `gw_dev_local`).
Default admin token: `dev-admin-token`. Override via `SAAS_JOB_API_*` env vars
(see `src/saas_job_api/config.py`).

## Quickstart / example walkthrough

With the server running (`python scripts/run_dev.py`), here's the full
seed → poll → acknowledge lifecycle against the dev defaults.

**1. Seed a job** (`X-Admin-Token: dev-admin-token`):

```bash
curl -s -i -X POST http://127.0.0.1:8000/admin/jobs \
  -H "X-Admin-Token: dev-admin-token" -H "Content-Type: application/json" \
  -d '{"jobType": "TLS_SCAN", "manifestVersion": "1.0", "payload": {"targetRef": "device_441", "credentialsRef": "cred_778"}}'
```

```
HTTP/1.1 200 OK
content-type: application/json

{"jobId":"job_22e1a9574943","state":"AVAILABLE"}
```

**2. Poll for it** (`Authorization: Bearer dev-gateway-token`) — reserves the
job for `reservation_ttl_seconds` (default 60s) and mints a `receiptToken`:

```bash
curl -s -i -X POST http://127.0.0.1:8000/gateway/v1/jobs/poll \
  -H "Authorization: Bearer dev-gateway-token" -H "Content-Type: application/json" \
  -d '{"maxJobs": 5}'
```

```
HTTP/1.1 200 OK
content-type: application/json

{
  "requestId": "8d474f38-d069-4c27-a595-d019e7aa39b8",
  "serverTime": "2026-08-18T10:38:19.981943Z",
  "receivedAt": "2026-08-18T10:38:19.981943Z",
  "pollAfterMs": 2000,
  "reservationUntil": "2026-08-18T10:39:19.981948Z",
  "jobs": [
    {
      "jobId": "job_22e1a9574943",
      "jobType": "TLS_SCAN",
      "manifestVersion": "1.0",
      "priority": 50,
      "scheduledAt": "2026-08-18T10:38:12.367330Z",
      "receiptToken": "CnDWrH6-qvDCOeNd7RM7N2oXyc8vywDK",
      "correlationId": "corr_131c5ccb9e1d",
      "payload": {"targetRef": "device_441", "credentialsRef": "cred_778"},
      "maxAttempts": 8,
      "traceId": null,
      "payloadHash": null
    }
  ]
}
```

A poll with nothing eligible to claim returns `204 No Content` with an empty
body instead (e.g. re-polling immediately after this, since the job above is
now `RESERVED` to this gateway).

**3. Acknowledge receipt**, using the `receiptToken` from step 2:

```bash
curl -s -i -X POST http://127.0.0.1:8000/gateway/v1/jobs/job_22e1a9574943/received \
  -H "Authorization: Bearer dev-gateway-token" -H "Content-Type: application/json" \
  -d '{"receiptToken": "CnDWrH6-qvDCOeNd7RM7N2oXyc8vywDK", "receivedAt": "2026-08-18T10:38:20Z"}'
```

```
HTTP/1.1 200 OK
content-type: application/json

{"jobId":"job_22e1a9574943","status":"ACKNOWLEDGED"}
```

**4. Confirm the state flip** via the admin listing:

```bash
curl -s http://127.0.0.1:8000/admin/jobs -H "X-Admin-Token: dev-admin-token"
```

```json
[{"jobId":"job_22e1a9574943","jobType":"TLS_SCAN","state":"ACKNOWLEDGED","reservedBy":"gw_dev_local","reservationUntil":"2026-08-18T10:39:19.981948+00:00","deliveryAttempts":1,"ackGatewayId":"gw_dev_local"}]
```

`job_22e1a9574943` went `AVAILABLE` → `RESERVED` (on poll) → `ACKNOWLEDGED`
(on receipt), with `deliveryAttempts: 1` — no redelivery was needed because
the receipt arrived before `reservationUntil`.

## Contract implemented

- `POST /gateway/v1/jobs/poll`
- `POST /gateway/v1/jobs/{jobId}/received`
- `POST /gateway/v1/jobs/received` (legacy flat-body alias — see below)
- `POST /admin/jobs`, `GET /admin/jobs`, `POST /admin/reset`, `POST /admin/faults` (dev/test only)

## Known contract gaps vs. the parent repo's current client

The parent repo's `HttpJobSource` (`src/certificate_discovery_engine/gateway_vm/http_source.py`)
predates this server and does not yet send/expect the full §9 contract. Two
small, explicitly-documented compatibility affordances exist here so the
*current* client can be verified end-to-end against a live instance of this
server without editing it:

1. **`receivedAt` on the poll response.** `HttpJobSource.poll()` unconditionally
   requires a `receivedAt` key and raises `ValueError` if it's absent — but
   the TDD's own poll response uses `serverTime`, not `receivedAt`, and a
   204-empty-poll response has no body at all. This server adds a
   `receivedAt` field that mirrors `serverTime` on every 200 response.
2. **Legacy `POST /gateway/v1/jobs/received` alias.** `HttpJobSource.acknowledge_received()`
   always POSTs `jobId` inside the JSON body to a flat URL — it never
   path-templates `{jobId}`, so the TDD's `/gateway/v1/jobs/{jobId}/received`
   route can never actually be reached by the current client.
3. **`received_url` must be set explicitly.** `HttpJobSource`'s default receipt-ack
   URL is `f"{poll_url.rstrip('/')}/received"`. When `poll_url` ends in `/poll`
   (as the TDD path does), that default becomes `.../jobs/poll/received`, not
   `.../jobs/received` — it doesn't strip the `/poll` segment. Callers must pass
   `received_url` explicitly (see `tests/test_e2e_with_existing_client.py`).

Contract tests in this repo hold the strict §9 shape (`test_poll_contract.py`,
`test_received_contract.py`); only the opt-in end-to-end test
(`tests/test_e2e_with_existing_client.py`) exercises the current client and
therefore only the compatibility surface.

**Contract surface the current client never reaches** (real, but untested by
the e2e test — follow-up once the client is updated to the full §9 contract):
`requestId`/`gatewayId`/`supportedJobTypes`/`supportedManifestVersions`/
`availableDispatchSlots`/`clientTime` on the poll request; the 204-empty-poll
response path; `reservationUntil`/`serverTime` on the poll response;
`gatewayId`/`payloadHash`/`localRecordVersion` on the receipt ack; and the
path-templated `/received` route.

## Testing

```bash
pytest
```

`tests/test_e2e_with_existing_client.py` imports the real `HttpJobSource`
from the parent repo's `src/` (added to `sys.path` in `conftest.py`) and is
skipped automatically if that import fails, e.g. when this directory is
copied out on its own.


## Production Deployment (Render)

This implementation supports production deployment on [Render.com](https://render.com) with persistent PostgreSQL storage and horizontal scaling.

### Prerequisites

- Render account (free tier available)
- GitHub repository (https://github.com/ashishkundan/saas-job-api)
- Production-ready secrets (admin token, gateway tokens)

### Deploy from render.yaml

1. **Push to GitHub** (if not already done):
   ```bash
   git push origin main
   ```

2. **Connect to Render**:
   - Go to https://dashboard.render.com
   - Click "New +" → "Blueprint"
   - Select your GitHub repository
   - Select `render.yaml` in this repo

3. **Set environment variables** (in Render dashboard after creating the blueprint):
   - `SAAS_JOB_API_ADMIN_TOKEN` — Generate a strong random token (e.g., `$(python -c 'import secrets; print(secrets.token_urlsafe(32))')`)
   - `SAAS_JOB_API_GATEWAY_TOKENS_JSON` — JSON map of tokens to gateway IDs, e.g. `{"your-token":"gw_prod_1"}`

4. **Deploy**:
   - Click "Deploy blueprint"
   - Render will automatically:
     - Create a managed PostgreSQL 15 database
     - Spin up 2 Web Service instances (auto-scaling 2-10)
     - Run database migrations on startup
     - Sync job state across all instances

### Architecture

- **Database**: Render-managed PostgreSQL 15 (auto-backups, HA failover)
- **API instances**: 2-10 Web Services (auto-scaling on CPU/memory)
- **Network**: Private network between API and DB (no internet exposure)
- **Logging**: Structured JSON logs (visible in Render dashboard)

### Monitoring

Jobs are persisted in the PostgreSQL `jobs` table. View job state via:
```bash
curl https://your-render-app.onrender.com/admin/jobs \
  -H "X-Admin-Token: $YOUR_ADMIN_TOKEN"
```

JSON structured logs appear in the Render dashboard with fields:
- `event`: "job_claimed", "job_acknowledged", "poll_no_jobs", "poll_fault_injected"
- `gateway_id`: Requesting gateway ID
- `job_id`: Job ID(s) affected
- `count`: Number of jobs (for claims)

### Troubleshooting

**"database connection failed"**: Verify `SAAS_JOB_API_DATABASE_URL` is set correctly (Render sets this automatically from the PostgreSQL service).

**"job not found"**: Jobs persist across restarts only if PostgreSQL service stays alive. Render's managed Postgres has auto-failover; manually deleting the service will lose all jobs.

**Horizontal scaling**: The database enforces atomicity via transactions (PostgreSQL ACID). Multiple instances safely claim, reserve, and acknowledge jobs without duplication. No manual coordination needed.

### Cost

- Render Free/Starter tier: $0-7/month (includes 1 free PostgreSQL instance)
- Standard tier: ~$50-200/month depending on scale
- See [Render pricing](https://render.com/pricing) for details
