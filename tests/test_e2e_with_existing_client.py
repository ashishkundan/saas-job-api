"""Opt-in verification that the parent repo's real Gateway VM poller client can
talk to a live instance of this server. Skipped automatically if the parent
package isn't importable (see conftest.py's sys.path shim) -- wired into CI
as the Phase 0.3 cross-repo smoke test (.github/workflows/cross-repo-smoke.yml),
which checks out certificate-discovery-engine as a sibling so this actually
runs instead of always skipping.

As of Phase 0.1 (2026-09-04), HttpJobSource's default (no received_url
override) correctly path-templates to POST /gateway/v1/jobs/{jobId}/received
-- the strict TDD section 9.2 route -- so this test now exercises that
route directly, proving the canonicalized contract works end-to-end against
a real server, not just against fakes. The deprecated flat-body legacy alias
route is intentionally not exercised here; it's scheduled for removal in
Phase 4.

Deliberately NOT exercised here (real contract surface the current client
never reaches -- see README.md "Known contract gaps"): 204-empty-poll,
requestId/gatewayId/supportedJobTypes/supportedManifestVersions/
availableDispatchSlots/clientTime on the poll request, gatewayId/payloadHash/
localRecordVersion on the ack, reservationUntil/serverTime.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

import httpx
import pytest
import uvicorn

from conftest import PARENT_CLIENT_AVAILABLE, make_test_settings
from saas_job_api.main import create_app

pytestmark = pytest.mark.skipif(
    not PARENT_CLIENT_AVAILABLE, reason="parent repo's certificate_discovery_engine package is not importable"
)

HOST = "127.0.0.1"
PORT = 8799
BASE_URL = f"http://{HOST}:{PORT}"
DEV_TOKEN = "e2e-gateway-token"
DEV_GATEWAY_ID = "gw_e2e"
ADMIN_TOKEN = "e2e-admin-token"


class ServerThread(threading.Thread):
    def __init__(self, app) -> None:
        super().__init__(daemon=True)
        config = uvicorn.Config(app=app, host=HOST, port=PORT, log_level="warning")
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        asyncio.run(self.server.serve())

    def wait_until_started(self, timeout: float = 5.0) -> None:
        import time

        start = time.monotonic()
        while not self.server.started:
            if time.monotonic() - start > timeout:
                raise RuntimeError("uvicorn server did not start in time")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(timeout=5.0)


@pytest.fixture
def live_server():
    app = create_app(
        settings=make_test_settings(
            gateway_tokens_json=f'{{"{DEV_TOKEN}": "{DEV_GATEWAY_ID}"}}',
            admin_token=ADMIN_TOKEN,
        )
    )
    thread = ServerThread(app)
    thread.start()
    thread.wait_until_started()
    yield
    thread.stop()


async def test_real_client_can_poll_and_acknowledge(live_server):
    from certificate_discovery_engine.gateway_vm.domain import DurableReceipt, PollRequest
    from certificate_discovery_engine.gateway_vm.http_source import HttpJobSource

    async with httpx.AsyncClient(base_url=BASE_URL) as admin_client:
        seed_resp = await admin_client.post(
            "/admin/jobs",
            json={"jobType": "TLS_SCAN", "manifestVersion": "1.0"},
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert seed_resp.status_code == 200
        seeded_job_id = seed_resp.json()["jobId"]

    source = HttpJobSource(
        poll_url=f"{BASE_URL}/gateway/v1/jobs/poll",
        # No received_url override: the default derives the strict path-style
        # route (.../jobs/{job_id}/received) directly from poll_url.
        api_token=DEV_TOKEN,
    )

    poll_response = await source.poll(
        PollRequest(capacity=5, batch_size=5, requested_at=datetime.now(timezone.utc))
    )

    assert len(poll_response.jobs) == 1
    job = poll_response.jobs[0]
    assert job.job_id == seeded_job_id

    await source.acknowledge_received(
        DurableReceipt(
            job_id=job.job_id,
            receipt_token=job.receipt_token,
            acknowledged_at=datetime.now(timezone.utc),
        )
    )

    async with httpx.AsyncClient(base_url=BASE_URL) as admin_client:
        list_resp = await admin_client.get("/admin/jobs", headers={"X-Admin-Token": ADMIN_TOKEN})
        record = next(r for r in list_resp.json() if r["jobId"] == seeded_job_id)
        assert record["state"] == "ACKNOWLEDGED"
