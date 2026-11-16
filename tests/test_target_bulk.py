"""POST /admin/v1/tenants/{tenantId}/targets/bulk - one server, many ports."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from saas_job_api.identity import AdminPrincipal, AdminRole
from saas_job_api.passwords import hash_password


async def _principal(app, client, *, role: AdminRole, tenant_id: str | None) -> dict[str, str]:
    name = f"u-{uuid.uuid4().hex[:8]}"
    await app.state.rbac_store.create_principal(AdminPrincipal(
        principal_id=str(uuid.uuid4()), username=name, password_hash=hash_password("pw"),
        role=role, created_at=datetime.now(timezone.utc), tenant_id=tenant_id,
    ))
    resp = await client.post("/admin/v1/login", json={"username": name, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


@pytest.fixture
async def admin(app, client: httpx.AsyncClient) -> dict[str, str]:
    return await _principal(app, client, role=AdminRole.PLATFORM_ADMIN, tenant_id=None)


@pytest.fixture
async def tenant(client: httpx.AsyncClient, admin) -> str:
    resp = await client.post("/admin/v1/tenants", json={"name": "Bulk"}, headers=admin)
    assert resp.status_code == 200, resp.text
    tenant_id = resp.json()["tenantId"]
    assert (await client.put(f"/admin/v1/tenants/{tenant_id}/plugins/tls-scanner", headers=admin)).status_code == 200
    return tenant_id


def _body(**over) -> dict:
    body = {"serverId": "web-01", "host": "10.0.0.5", "ports": [443, 8443, 9443],
            "pluginRef": "tls-scanner", "pluginVersion": "1.0"}
    body.update(over)
    return body


async def test_creates_one_target_per_port(client, admin, tenant, app) -> None:
    resp = await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk", json=_body(), headers=admin)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["serverId"], data["created"], data["existing"], data["conflicts"]) == ("web-01", 3, 0, 0)
    assert [(r["port"], r["targetId"], r["status"]) for r in data["results"]] == [
        (443, "web-01-443", "created"), (8443, "web-01-8443", "created"), (9443, "web-01-9443", "created")]
    listed = (await client.get(f"/admin/v1/tenants/{tenant}/targets", headers=admin)).json()
    by_id = {t["targetId"]: t for t in listed}
    assert by_id["web-01-8443"]["host"] == "10.0.0.5"
    assert by_id["web-01-8443"]["port"] == 8443
    assert by_id["web-01-8443"]["name"] == "web-01 port 8443"
    assert by_id["web-01-8443"]["effectivePluginVersion"] == "1.0"
    events = [e for e in await app.state.audit_store.list_recent(limit=100) if e.event_type == "TARGET_CREATED"]
    assert {e.resource_id for e in events} == {"web-01-443", "web-01-8443", "web-01-9443"}


async def test_repeat_is_idempotent_and_adds_only_new_ports(client, admin, tenant) -> None:
    await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk", json=_body(), headers=admin)

    resp = await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk",
                             json=_body(ports=[443, 8443, 9443, 10443]), headers=admin)

    data = resp.json()
    assert (data["created"], data["existing"], data["conflicts"]) == (1, 3, 0)
    assert [r["status"] for r in data["results"]] == ["exists", "exists", "exists", "created"]


async def test_existing_target_with_other_settings_is_a_conflict_and_unchanged(client, admin, tenant) -> None:
    await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk", json=_body(ports=[443]), headers=admin)

    resp = await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk",
                             json=_body(host="10.0.0.6", ports=[443, 8443]), headers=admin)

    data = resp.json()
    assert (data["created"], data["conflicts"]) == (1, 1)
    assert data["results"][0]["status"] == "conflict" and "10.0.0.5" in data["results"][0]["detail"]
    kept = (await client.get(f"/admin/v1/tenants/{tenant}/targets/web-01-443", headers=admin)).json()
    assert kept["host"] == "10.0.0.5"


async def test_not_entitled_creates_nothing(client, admin, tenant) -> None:
    resp = await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk",
                             json=_body(pluginRef="linux-collector"), headers=admin)

    assert resp.status_code == 400
    assert (await client.get(f"/admin/v1/tenants/{tenant}/targets", headers=admin)).json() == []


@pytest.mark.parametrize("over", [
    {"ports": []},
    {"ports": [443, 443]},
    {"ports": [0]},
    {"ports": [65536]},
    {"serverId": "bad id"},
    {"serverId": "x" * 45},
    {"unexpected": 1},
])
async def test_invalid_requests_are_rejected(client, admin, tenant, over) -> None:
    resp = await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk", json=_body(**over), headers=admin)

    assert resp.status_code in (400, 422), resp.text
    assert (await client.get(f"/admin/v1/tenants/{tenant}/targets", headers=admin)).json() == []


async def test_tenant_admin_only_for_own_tenant_and_viewer_cannot_write(app, client, admin, tenant) -> None:
    other = (await client.post("/admin/v1/tenants", json={"name": "Other"}, headers=admin)).json()["tenantId"]
    own_admin = await _principal(app, client, role=AdminRole.TENANT_ADMIN, tenant_id=tenant)
    viewer = await _principal(app, client, role=AdminRole.TENANT_VIEWER, tenant_id=tenant)

    assert (await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk", json=_body(), headers=own_admin)).status_code == 200
    assert (await client.post(f"/admin/v1/tenants/{other}/targets/bulk", json=_body(), headers=own_admin)).status_code == 403
    assert (await client.post(f"/admin/v1/tenants/{tenant}/targets/bulk",
                              json=_body(serverId="web-02"), headers=viewer)).status_code == 403
