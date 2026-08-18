from __future__ import annotations


async def test_create_list_reset_round_trip(client, admin_headers):
    create_resp = await client.post(
        "/admin/jobs", json={"jobType": "TLS_SCAN", "manifestVersion": "1.0"}, headers=admin_headers
    )
    assert create_resp.status_code == 200
    job_id = create_resp.json()["jobId"]

    list_resp = await client.get("/admin/jobs", headers=admin_headers)
    assert list_resp.status_code == 200
    listed_ids = [j["jobId"] for j in list_resp.json()]
    assert job_id in listed_ids

    reset_resp = await client.post("/admin/reset", headers=admin_headers)
    assert reset_resp.status_code == 200

    after_reset = await client.get("/admin/jobs", headers=admin_headers)
    assert after_reset.json() == []


async def test_create_job_honors_explicit_job_id_and_defaults(client, admin_headers):
    resp = await client.post(
        "/admin/jobs",
        json={"jobId": "job_explicit", "jobType": "WINDOWS_CERT_SCAN", "manifestVersion": "1.1", "priority": 90},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["jobId"] == "job_explicit"


async def test_create_job_duplicate_id_is_rejected(client, admin_headers):
    body = {"jobId": "dup", "jobType": "TLS_SCAN", "manifestVersion": "1.0"}
    first = await client.post("/admin/jobs", json=body, headers=admin_headers)
    assert first.status_code == 200

    second = await client.post("/admin/jobs", json=body, headers=admin_headers)
    assert second.status_code == 500  # ValueError from JobStore.seed -> generic handler
