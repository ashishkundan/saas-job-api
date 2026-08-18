from __future__ import annotations


async def test_fault_injection_forces_next_poll_status_and_retry_after(client, admin_headers, gateway_headers):
    arm_resp = await client.post(
        "/admin/faults", json={"nextPollStatus": 429, "retryAfterSeconds": 5}, headers=admin_headers
    )
    assert arm_resp.status_code == 200

    faulted = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)
    assert faulted.status_code == 429
    assert faulted.headers["retry-after"] == "5"

    # Fault is one-shot: the following poll behaves normally (204, no jobs seeded).
    recovered = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)
    assert recovered.status_code == 204


async def test_fault_injection_supports_5xx(client, admin_headers, gateway_headers):
    await client.post("/admin/faults", json={"nextPollStatus": 503}, headers=admin_headers)

    resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)

    assert resp.status_code == 503


async def test_full_status_code_table(client, admin_headers, gateway_headers):
    # 400: malformed body
    bad = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": "nope"}, headers=gateway_headers)
    assert bad.status_code == 400

    # 401: no auth
    unauth = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20})
    assert unauth.status_code == 401

    # 403: gatewayId mismatch
    forbidden = await client.post(
        "/gateway/v1/jobs/poll", json={"maxJobs": 20, "gatewayId": "not-me"}, headers=gateway_headers
    )
    assert forbidden.status_code == 403

    # 409: unknown job on ack
    conflict = await client.post(
        "/gateway/v1/jobs/nope/received",
        json={"receiptToken": "x", "receivedAt": "2026-08-02T01:30:00Z"},
        headers=gateway_headers,
    )
    assert conflict.status_code == 409
