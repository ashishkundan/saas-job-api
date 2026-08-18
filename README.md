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
