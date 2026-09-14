"""GET /admin/v1/audit + audit wiring across registration, tenant/target/
schedule mutations, result submission, and RBAC-gated admin actions
(Phase 2.7)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from conftest import DEV_GATEWAY_ID
from saas_job_api.identity import AdminPrincipal, AdminRole
from saas_job_api.passwords import hash_password

CERT = {
    "subject": "CN=example.internal",
    "issuer": "CN=Corporate-CA",
    "serialNumber": "012345",
    "validFrom": "2026-01-01T00:00:00Z",
    "validTo": "2027-01-01T00:00:00Z",
    "fingerprint": "abc123",
}


async def _create_principal(app, *, username: str, password: str, role: AdminRole, tenant_id: str | None) -> None:
    await app.state.rbac_store.create_principal(
        AdminPrincipal(
            principal_id=str(uuid.uuid4()),
            username=username,
            password_hash=hash_password(password),
            role=role,
            created_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
        )
    )


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    resp = await client.post("/admin/v1/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["accessToken"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def platform_admin_token(app, client: httpx.AsyncClient) -> str:
    await _create_principal(app, username="platform-1", password="pw-platform", role=AdminRole.PLATFORM_ADMIN, tenant_id=None)
    return await _login(client, "platform-1", "pw-platform")


@pytest.fixture
async def tenant_a(client: httpx.AsyncClient, platform_admin_token: str) -> dict:
    resp = await client.post("/admin/v1/tenants", json={"name": "Tenant A"}, headers=_auth(platform_admin_token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
async def tenant_a_admin_token(app, client: httpx.AsyncClient, tenant_a: dict) -> str:
    await _create_principal(
        app, username="tenant-a-admin", password="pw-a-admin", role=AdminRole.TENANT_ADMIN, tenant_id=tenant_a["tenantId"]
    )
    return await _login(client, "tenant-a-admin", "pw-a-admin")


async def _events(app) -> list:
    return await app.state.audit_store.list_recent(limit=1000)


async def _event_types(app) -> list[str]:
    return [e.event_type for e in await _events(app)]


# ---- GET /admin/v1/audit RBAC ----------------------------------------------


async def test_audit_endpoint_requires_platform_admin(client, tenant_a_admin_token) -> None:
    resp = await client.get("/admin/v1/audit", headers=_auth(tenant_a_admin_token))

    assert resp.status_code == 403


async def test_audit_endpoint_requires_authentication(client) -> None:
    resp = await client.get("/admin/v1/audit")

    assert resp.status_code == 401


async def test_audit_endpoint_returns_events_for_platform_admin(client, platform_admin_token) -> None:
    # platform_admin login itself is an audited event.
    resp = await client.get("/admin/v1/audit", headers=_auth(platform_admin_token))

    assert resp.status_code == 200
    types = [e["eventType"] for e in resp.json()]
    assert "ADMIN_LOGIN_SUCCEEDED" in types


async def test_audit_endpoint_filters_by_tenant_id(client, platform_admin_token, tenant_a, app) -> None:
    resp = await client.get(f"/admin/v1/audit?tenantId={tenant_a['tenantId']}", headers=_auth(platform_admin_token))

    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    assert all(e["tenantId"] == tenant_a["tenantId"] for e in events)


# ---- Wiring: tenant/target/schedule mutations ------------------------------


async def test_tenant_create_and_delete_are_audited(client, platform_admin_token, app) -> None:
    create_resp = await client.post("/admin/v1/tenants", json={"name": "Audited Co"}, headers=_auth(platform_admin_token))
    tenant_id = create_resp.json()["tenantId"]
    await client.delete(f"/admin/v1/tenants/{tenant_id}", headers=_auth(platform_admin_token))

    events = [e for e in await _events(app) if e.resource_id == tenant_id]
    assert [e.event_type for e in events] == ["TENANT_CREATED", "TENANT_DELETED"]


async def test_target_create_and_delete_are_audited(client, tenant_a, tenant_a_admin_token, app) -> None:
    target_payload = {"name": "web-01", "host": "10.0.0.5", "port": 443, "pluginRef": "tls-scanner", "pluginVersion": "2.1"}
    create_resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=target_payload, headers=_auth(tenant_a_admin_token)
    )
    target_id = create_resp.json()["targetId"]
    await client.delete(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets/{target_id}", headers=_auth(tenant_a_admin_token))

    events = [e for e in await _events(app) if e.resource_id == target_id]
    assert [e.event_type for e in events] == ["TARGET_CREATED", "TARGET_DELETED"]
    assert all(e.tenant_id == tenant_a["tenantId"] for e in events)


async def test_schedule_create_and_delete_are_audited(client, tenant_a, tenant_a_admin_token, app) -> None:
    target_payload = {"name": "web-01", "host": "10.0.0.5", "port": 443, "pluginRef": "tls-scanner", "pluginVersion": "2.1"}
    target_resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=target_payload, headers=_auth(tenant_a_admin_token)
    )
    target_id = target_resp.json()["targetId"]

    schedule_payload = {"targetId": target_id, "jobType": "tls-scan", "manifestVersion": "1.0", "intervalSeconds": 3600}
    create_resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules", json=schedule_payload, headers=_auth(tenant_a_admin_token)
    )
    schedule_id = create_resp.json()["scheduleId"]
    await client.delete(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules/{schedule_id}", headers=_auth(tenant_a_admin_token)
    )

    events = [e for e in await _events(app) if e.resource_id == schedule_id]
    assert [e.event_type for e in events] == ["SCHEDULE_CREATED", "SCHEDULE_DELETED"]


# ---- Wiring: result submission ---------------------------------------------


async def _seed_claim_and_ack(client, admin_headers, gateway_headers, **job_overrides):
    body = {"jobType": "TLS_SCAN", "manifestVersion": "1.0"}
    body.update(job_overrides)
    seed_resp = await client.post("/admin/jobs", json=body, headers=admin_headers)
    job_id = seed_resp.json()["jobId"]
    poll_resp = await client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=gateway_headers)
    job = poll_resp.json()["jobs"][0]
    await client.post(
        f"/gateway/v1/jobs/{job_id}/received",
        json={"receiptToken": job["receiptToken"], "receivedAt": "2026-08-02T01:30:00Z"},
        headers=gateway_headers,
    )
    return job_id


async def test_result_submission_is_audited_once_not_on_retry(client, admin_headers, gateway_headers, app) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)
    payload = {"attemptToken": "attempt-1", "pluginId": "tls-scanner", "pluginVersion": "2.1", "certificates": [CERT]}

    await client.post(f"/gateway/v1/jobs/{job_id}/results", json=payload, headers=gateway_headers)
    await client.post(f"/gateway/v1/jobs/{job_id}/results", json=payload, headers=gateway_headers)

    events = [e for e in await _events(app) if e.resource_id == job_id and e.event_type == "RESULT_SUBMITTED"]
    assert len(events) == 1
    assert events[0].actor == DEV_GATEWAY_ID
    assert events[0].detail["recordCount"] == 1


async def test_interrupted_report_is_audited_only_when_reissued(client, admin_headers, gateway_headers, app) -> None:
    job_id = await _seed_claim_and_ack(client, admin_headers, gateway_headers)

    await client.post(f"/gateway/v1/jobs/{job_id}/interrupted", json={"attemptToken": "attempt-1"}, headers=gateway_headers)
    # second call: job is no longer ACKNOWLEDGED (already AVAILABLE) - a no-op.
    await client.post(f"/gateway/v1/jobs/{job_id}/interrupted", json={"attemptToken": "attempt-1"}, headers=gateway_headers)

    events = [e for e in await _events(app) if e.resource_id == job_id and e.event_type == "JOB_INTERRUPTED_REPORTED"]
    assert len(events) == 1


# ---- Wiring: login + registration ------------------------------------------


async def test_login_success_and_failure_are_audited(client, app) -> None:
    await _create_principal(app, username="someone", password="correct-pw", role=AdminRole.PLATFORM_ADMIN, tenant_id=None)

    await client.post("/admin/v1/login", json={"username": "someone", "password": "wrong-pw"})
    await client.post("/admin/v1/login", json={"username": "someone", "password": "correct-pw"})

    types = await _event_types(app)
    assert "ADMIN_LOGIN_FAILED" in types
    assert "ADMIN_LOGIN_SUCCEEDED" in types


async def test_login_failure_audit_never_records_the_password(client, app) -> None:
    await client.post("/admin/v1/login", json={"username": "nobody", "password": "super-secret-password"})

    events = await _events(app)
    for event in events:
        assert "super-secret-password" not in str(event.detail)
        assert "super-secret-password" != event.actor


async def test_enrollment_token_issuance_is_audited(client, platform_admin_token, app) -> None:
    resp = await client.post("/admin/v1/enrollment-tokens", headers=_auth(platform_admin_token))
    assert resp.status_code == 200, resp.text

    types = await _event_types(app)
    assert "ENROLLMENT_TOKEN_ISSUED" in types
