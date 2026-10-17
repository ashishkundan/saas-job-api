from __future__ import annotations

from conftest import (
    TEST_JOB_TYPE,
    TEST_PLUGIN_REF,
    TEST_TARGET_ID,
    TEST_TENANT_ID,
    job_body,
    seed_fixture_tenant_and_target,
)


async def test_create_list_reset_round_trip(client, admin_headers):
    create_resp = await client.post("/admin/jobs", json=job_body(), headers=admin_headers)
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
        json=job_body(jobId="job_explicit", manifestVersion="1.1", priority=90),
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["jobId"] == "job_explicit"


async def test_create_job_duplicate_id_is_rejected(client, admin_headers):
    body = job_body(jobId="dup")
    first = await client.post("/admin/jobs", json=body, headers=admin_headers)
    assert first.status_code == 200

    second = await client.post("/admin/jobs", json=body, headers=admin_headers)
    assert second.status_code == 500  # ValueError from JobStore.seed -> generic handler


async def test_create_job_derives_payload_and_job_type_from_the_target(client, admin_headers, app):
    resp = await client.post("/admin/jobs", json=job_body(timeoutSeconds=120), headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["jobType"] == TEST_JOB_TYPE
    record = await app.state.store.get(resp.json()["jobId"])
    assert record.tenant_id == TEST_TENANT_ID
    assert record.target_id == TEST_TARGET_ID
    assert record.job_type == TEST_JOB_TYPE
    assert record.payload == {
        "pluginRef": TEST_PLUGIN_REF,
        "pluginVersion": "1.0",
        "targetEndpoint": "192.0.2.10:443",
        "credentialRef": None,
        "tenantId": TEST_TENANT_ID,
        "targetId": TEST_TARGET_ID,
        "timeoutSeconds": 120,
    }


async def test_create_job_accepts_a_matching_explicit_job_type(client, admin_headers):
    resp = await client.post("/admin/jobs", json=job_body(jobType=TEST_JOB_TYPE), headers=admin_headers)
    assert resp.status_code == 200


async def test_create_job_rejects_a_job_type_that_does_not_match_the_target(client, admin_headers, app):
    resp = await client.post("/admin/jobs", json=job_body(jobType="windows-collector-scan"), headers=admin_headers)

    assert resp.status_code == 400
    assert await app.state.store.list_all() == []


async def test_create_job_requires_tenant_id(client, admin_headers):
    resp = await client.post("/admin/jobs", json={"targetId": TEST_TARGET_ID}, headers=admin_headers)
    assert resp.status_code == 400


async def test_create_job_requires_target_id(client, admin_headers):
    resp = await client.post("/admin/jobs", json={"tenantId": TEST_TENANT_ID}, headers=admin_headers)
    assert resp.status_code == 400


async def test_create_job_rejects_a_free_form_payload(client, admin_headers, app):
    resp = await client.post(
        "/admin/jobs",
        json=job_body(payload={"pluginRef": "windows-collector", "targetEndpoint": "10.0.0.1:5985"}),
        headers=admin_headers,
    )

    assert resp.status_code == 400
    assert await app.state.store.list_all() == []


async def test_create_job_for_an_unknown_tenant_is_404(client, admin_headers):
    resp = await client.post("/admin/jobs", json=job_body(tenantId="tenant-nope"), headers=admin_headers)
    assert resp.status_code == 404


async def test_create_job_for_an_unknown_target_is_404(client, admin_headers):
    resp = await client.post("/admin/jobs", json=job_body(targetId="target-nope"), headers=admin_headers)
    assert resp.status_code == 404


async def test_create_job_cannot_use_another_tenants_target(client, admin_headers, app):
    await seed_fixture_tenant_and_target(app, tenant_id="tenant-other", target_id="target-other")

    resp = await client.post(
        "/admin/jobs", json=job_body(tenantId=TEST_TENANT_ID, targetId="target-other"), headers=admin_headers
    )

    assert resp.status_code == 404


async def test_list_jobs_filters_by_tenant(client, admin_headers, app):
    await seed_fixture_tenant_and_target(app, tenant_id="tenant-other", target_id="target-other")
    mine = await client.post("/admin/jobs", json=job_body(), headers=admin_headers)
    await client.post(
        "/admin/jobs", json=job_body(tenantId="tenant-other", targetId="target-other"), headers=admin_headers
    )

    resp = await client.get("/admin/jobs", params={"tenantId": TEST_TENANT_ID}, headers=admin_headers)

    assert [j["jobId"] for j in resp.json()] == [mine.json()["jobId"]]
    assert resp.json()[0]["tenantId"] == TEST_TENANT_ID
    assert resp.json()[0]["targetId"] == TEST_TARGET_ID
