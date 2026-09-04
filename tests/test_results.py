"""POST /gateway/v1/jobs/{jobId}/results + /interrupted (Phase 2.6)."""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import DEV_GATEWAY_ID, DEV_TOKEN, make_test_settings
from saas_job_api.domain import JobState
from saas_job_api.main import create_app

CERT = {
    "subject": "CN=example.internal",
    "issuer": "CN=Corporate-CA",
    "serialNumber": "012345",
    "validFrom": "2026-01-01T00:00:00Z",
    "validTo": "2027-01-01T00:00:00Z",
    "fingerprint": "abc123",
}


async def _seed_claim_and_ack(client, admin_headers, gateway_headers, **job_overrides):
    body = {"jobType": "TLS_SCAN", "manifestVersion": "1.0"}
    body.update(job_overrides)
    seed_resp = await client.post("/admin/jobs", json=body, headers=admin_headers)
    job_id = seed_resp.json()["jobId"]

    poll_resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)
    job = poll_resp.json()["jobs"][0]
    receipt_token = job["receiptToken"]

    ack_resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/received",
        json={"receiptToken": receipt_token, "receivedAt": "2026-08-02T01:30:00Z"},
        headers=gateway_headers,
    )
    assert ack_resp.status_code == 200
    return job_id


async def _job_state(client, admin_headers, job_id) -> str:
    listing = await client.get("/admin/jobs", headers=admin_headers)
    job = next(j for j in listing.json() if j["jobId"] == job_id)
    return job["state"]


async def test_submit_result_happy_path(client, admin_headers, gateway_headers) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/results",
        json={"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": [CERT]},
        headers=gateway_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"accepted": True, "dedupe": False, "recordCount": 1}
    assert await _job_state(client, admin_headers, job_id) == "COMPLETED"


async def test_submit_result_is_idempotent_on_a_retried_submission(client, admin_headers, gateway_headers) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)
    payload = {"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": [CERT]}

    first = await client.post(f"/gateway/v1/jobs/{job_id}/results", json=payload, headers=gateway_headers)
    second = await client.post(f"/gateway/v1/jobs/{job_id}/results", json=payload, headers=gateway_headers)

    assert first.json() == {"accepted": True, "dedupe": False, "recordCount": 1}
    assert second.json() == {"accepted": True, "dedupe": True, "recordCount": 1}
    # job stays COMPLETED, not re-processed
    assert await _job_state(client, admin_headers, job_id) == "COMPLETED"


async def test_submit_result_does_not_duplicate_inventory_rows(client, admin_headers, gateway_headers, app) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)
    payload = {"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": [CERT]}

    await client.post(f"/gateway/v1/jobs/{job_id}/results", json=payload, headers=gateway_headers)
    await client.post(f"/gateway/v1/jobs/{job_id}/results", json=payload, headers=gateway_headers)

    records = list(app.state.inventory_store._records.values())
    assert len([r for r in records if r.job_id == job_id]) == 1


async def test_submit_result_records_tenant_and_target_from_job_payload(client, admin_headers, gateway_headers, app) -> None:
    job_id = await _seed_claim_and_ack(
        client, admin_headers, gateway_headers, payload={"tenantId": "tenant-42", "targetId": "target-7"}
    )

    await client.post(
        f"/gateway/v1/jobs/{job_id}/results",
        json={"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": [CERT]},
        headers=gateway_headers,
    )

    inventory = await app.state.inventory_store.list_by_tenant("tenant-42", limit=10)
    assert len(inventory) == 1
    assert inventory[0].target_id == "target-7"
    assert inventory[0].fingerprint == "abc123"


async def test_submit_result_for_unknown_job_is_404(client, gateway_headers) -> None:
    resp = await client.post(
        "/gateway/v1/jobs/no-such-job/results",
        json={"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": []},
        headers=gateway_headers,
    )

    assert resp.status_code == 404


async def test_submit_result_rejects_a_job_id_mismatch_between_path_and_body(client, admin_headers, gateway_headers) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/results",
        json={
            "jobId": "different-job-id",
            "attemptToken": "attempt-1",
            "pluginId": "tls-scanner",
            "pluginVersion": "2.1",
            "certificates": [],
        },
        headers=gateway_headers,
    )

    assert resp.status_code == 400


async def test_submit_result_without_auth_is_401(client, admin_headers, gateway_headers) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/results",
        json={"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": []},
    )

    assert resp.status_code == 401


async def test_submit_result_from_a_different_gateway_is_409() -> None:
    other_token = "other-gateway-token"
    other_gateway_id = "gw_other"
    app = create_app(
        settings=make_test_settings(
            gateway_tokens_json=json.dumps({DEV_TOKEN: DEV_GATEWAY_ID, other_token: other_gateway_id})
        )
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = {"X-Admin-Token": "test-admin-token"}
            gateway_headers = {"Authorization": f"Bearer {DEV_TOKEN}"}
            other_headers = {"Authorization": f"Bearer {other_token}"}

            job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)

            resp = await client.post(
                f"/gateway/v1/jobs/{job_id}/results",
                json={"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": []},
                headers=other_headers,
            )

            assert resp.status_code == 409


async def test_report_interrupted_reissues_the_job(client, admin_headers, gateway_headers) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/interrupted", json={"attemptToken": "attempt-1"}, headers=gateway_headers
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "reissued"
    assert await _job_state(client, admin_headers, job_id) == "AVAILABLE"


async def test_report_interrupted_job_becomes_claimable_again(client, admin_headers, gateway_headers) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)
    await client.post(f"/gateway/v1/jobs/{job_id}/interrupted", json={"attemptToken": "attempt-1"}, headers=gateway_headers)

    poll_resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)

    assert poll_resp.status_code == 200
    assert poll_resp.json()["jobs"][0]["jobId"] == job_id


async def test_report_interrupted_for_a_not_acknowledged_job_is_a_noop(client, admin_headers, gateway_headers) -> None:
    seed_resp = await client.post("/admin/jobs", json={"jobType": "TLS_SCAN", "manifestVersion": "1.0"}, headers=admin_headers)
    job_id = seed_resp.json()["jobId"]

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/interrupted", json={"attemptToken": "attempt-1"}, headers=gateway_headers
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "noop"
    assert await _job_state(client, admin_headers, job_id) == "AVAILABLE"


async def test_report_interrupted_for_an_unknown_job_is_a_noop_not_404(client, gateway_headers) -> None:
    resp = await client.post(
        "/gateway/v1/jobs/no-such-job/interrupted", json={"attemptToken": "attempt-1"}, headers=gateway_headers
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "noop"


async def test_a_completed_job_is_never_reissued_as_orphaned(client, admin_headers, gateway_headers, app, clock) -> None:
    """Regression proof for the exact bug this phase's ordering (mark
    completed before this job's gateway could ever be checked again) is
    meant to prevent: once a result is recorded, the job must never come
    back from reissue_orphaned_jobs() (2.5) even if its gateway later goes
    unreachable/fails - it already finished."""
    from datetime import timedelta

    from saas_job_api.health import GatewayStatus
    from saas_job_api.orchestrator.scheduler_tick import reissue_orphaned_jobs

    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)
    await client.post(
        f"/gateway/v1/jobs/{job_id}/results",
        json={"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": [CERT]},
        headers=gateway_headers,
    )
    assert await _job_state(client, admin_headers, job_id) == "COMPLETED"

    await app.state.health_store.upsert(
        GatewayStatus(
            gateway_id=DEV_GATEWAY_ID, tenant_id=None, last_heartbeat_at=clock.now() - timedelta(seconds=3000),
            gateway_version="1.0", container_runtime_status="DOWN", last_successful_job_at=None, last_error=None,
        )
    )

    reissued = await reissue_orphaned_jobs(
        job_store=app.state.store, health_store=app.state.health_store, clock=clock, sla_seconds=1.0,
        degraded_after_seconds=90.0, unreachable_after_seconds=300.0, failed_after_seconds=1800.0,
    )

    assert reissued == 0
    assert await _job_state(client, admin_headers, job_id) == "COMPLETED"
