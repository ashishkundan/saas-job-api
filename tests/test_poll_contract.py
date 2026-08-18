from __future__ import annotations

from conftest import DEV_GATEWAY_ID


async def _seed_job(client, admin_headers, **overrides):
    body = {"jobType": "TLS_SCAN", "manifestVersion": "1.0"}
    body.update(overrides)
    resp = await client.post("/admin/jobs", json=body, headers=admin_headers)
    assert resp.status_code == 200
    return resp.json()["jobId"]


async def test_full_tdd_shaped_poll_returns_matching_jobs(client, admin_headers, gateway_headers):
    await _seed_job(client, admin_headers)

    resp = await client.post(
        "/gateway/v1/jobs/poll",
        json={
            "requestId": "req_1",
            "gatewayId": DEV_GATEWAY_ID,
            "maxJobs": 20,
            "supportedJobTypes": ["TLS_SCAN"],
            "supportedManifestVersions": ["1.0"],
            "availableDispatchSlots": 8,
            "clientTime": "2026-08-02T01:30:00Z",
        },
        headers=gateway_headers,
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["requestId"] == "req_1"
    assert "serverTime" in payload
    assert "pollAfterMs" in payload
    assert "reservationUntil" in payload
    assert len(payload["jobs"]) == 1
    job = payload["jobs"][0]
    assert job["jobType"] == "TLS_SCAN"
    assert job["manifestVersion"] == "1.0"
    assert job["receiptToken"]


async def test_poll_compatibility_shim_includes_received_at(client, admin_headers, gateway_headers):
    await _seed_job(client, admin_headers)

    resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)

    assert resp.status_code == 200
    assert "receivedAt" in resp.json()


async def test_poll_with_no_eligible_jobs_returns_204_empty(client, gateway_headers):
    resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)

    assert resp.status_code == 204
    assert resp.content == b""


async def test_poll_missing_bearer_is_401(client):
    resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20})
    assert resp.status_code == 401


async def test_poll_unknown_bearer_is_401(client):
    resp = await client.post(
        "/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401


async def test_poll_mismatched_body_gateway_id_is_403(client, gateway_headers):
    resp = await client.post(
        "/gateway/v1/jobs/poll",
        json={"maxJobs": 20, "gatewayId": "someone-else"},
        headers=gateway_headers,
    )
    assert resp.status_code == 403


async def test_poll_malformed_body_is_400_not_422(client, gateway_headers):
    resp = await client.post(
        "/gateway/v1/jobs/poll",
        json={"maxJobs": "not-a-number"},
        headers=gateway_headers,
    )
    assert resp.status_code == 400
