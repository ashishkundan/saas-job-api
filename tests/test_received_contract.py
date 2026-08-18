from __future__ import annotations

from conftest import DEV_GATEWAY_ID


async def _seed_and_claim(client, admin_headers, gateway_headers):
    seed_resp = await client.post(
        "/admin/jobs", json={"jobType": "TLS_SCAN", "manifestVersion": "1.0"}, headers=admin_headers
    )
    job_id = seed_resp.json()["jobId"]

    poll_resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)
    job = poll_resp.json()["jobs"][0]
    assert job["jobId"] == job_id
    return job_id, job["receiptToken"]


async def test_received_happy_path(client, admin_headers, gateway_headers):
    job_id, receipt_token = await _seed_and_claim(client, admin_headers, gateway_headers)

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/received",
        json={
            "gatewayId": DEV_GATEWAY_ID,
            "receiptToken": receipt_token,
            "receivedAt": "2026-08-02T01:30:00.328Z",
            "payloadHash": "sha256:abc",
            "localRecordVersion": 1,
        },
        headers=gateway_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"jobId": job_id, "status": "ACKNOWLEDGED"}


async def test_received_repeat_ack_is_idempotent_not_409(client, admin_headers, gateway_headers):
    job_id, receipt_token = await _seed_and_claim(client, admin_headers, gateway_headers)
    body = {"receiptToken": receipt_token, "receivedAt": "2026-08-02T01:30:00.328Z"}

    first = await client.post(f"/gateway/v1/jobs/{job_id}/received", json=body, headers=gateway_headers)
    second = await client.post(f"/gateway/v1/jobs/{job_id}/received", json=body, headers=gateway_headers)

    assert first.status_code == 200
    assert second.status_code == 200


async def test_received_wrong_token_is_409(client, admin_headers, gateway_headers):
    job_id, _ = await _seed_and_claim(client, admin_headers, gateway_headers)

    resp = await client.post(
        f"/gateway/v1/jobs/{job_id}/received",
        json={"receiptToken": "wrong-token", "receivedAt": "2026-08-02T01:30:00.328Z"},
        headers=gateway_headers,
    )

    assert resp.status_code == 409


async def test_received_unknown_job_is_409(client, gateway_headers):
    resp = await client.post(
        "/gateway/v1/jobs/does_not_exist/received",
        json={"receiptToken": "whatever", "receivedAt": "2026-08-02T01:30:00.328Z"},
        headers=gateway_headers,
    )

    assert resp.status_code == 409


async def test_legacy_alias_route_accepts_job_id_in_body(client, admin_headers, gateway_headers):
    job_id, receipt_token = await _seed_and_claim(client, admin_headers, gateway_headers)

    resp = await client.post(
        "/gateway/v1/jobs/received",
        json={
            "jobId": job_id,
            "receiptToken": receipt_token,
            "acknowledgedAt": "2026-08-02T01:30:00.328Z",
        },
        headers=gateway_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"jobId": job_id, "status": "ACKNOWLEDGED"}


async def test_legacy_alias_route_without_job_id_is_400(client, gateway_headers):
    resp = await client.post(
        "/gateway/v1/jobs/received",
        json={"receiptToken": "whatever", "receivedAt": "2026-08-02T01:30:00.328Z"},
        headers=gateway_headers,
    )

    assert resp.status_code == 400
