"""Tenant / Target / Schedule CRUD + tenant-scoped RBAC (Phase 2.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from saas_job_api.identity import AdminPrincipal, AdminRole
from saas_job_api.passwords import hash_password


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
async def tenant_b(client: httpx.AsyncClient, platform_admin_token: str) -> dict:
    resp = await client.post("/admin/v1/tenants", json={"name": "Tenant B"}, headers=_auth(platform_admin_token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
async def tenant_a_admin_token(app, client: httpx.AsyncClient, tenant_a: dict) -> str:
    await _create_principal(
        app, username="tenant-a-admin", password="pw-a-admin", role=AdminRole.TENANT_ADMIN, tenant_id=tenant_a["tenantId"]
    )
    return await _login(client, "tenant-a-admin", "pw-a-admin")


@pytest.fixture
async def tenant_a_viewer_token(app, client: httpx.AsyncClient, tenant_a: dict) -> str:
    await _create_principal(
        app, username="tenant-a-viewer", password="pw-a-viewer", role=AdminRole.TENANT_VIEWER, tenant_id=tenant_a["tenantId"]
    )
    return await _login(client, "tenant-a-viewer", "pw-a-viewer")


@pytest.fixture
async def tenant_b_admin_token(app, client: httpx.AsyncClient, tenant_b: dict) -> str:
    await _create_principal(
        app, username="tenant-b-admin", password="pw-b-admin", role=AdminRole.TENANT_ADMIN, tenant_id=tenant_b["tenantId"]
    )
    return await _login(client, "tenant-b-admin", "pw-b-admin")


# ---- Tenant CRUD ----------------------------------------------------------


async def test_platform_admin_creates_a_tenant(client: httpx.AsyncClient, platform_admin_token: str) -> None:
    resp = await client.post("/admin/v1/tenants", json={"name": "Acme"}, headers=_auth(platform_admin_token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Acme"
    assert body["isActive"] is True
    assert body["tenantId"]


async def test_creating_a_tenant_with_a_duplicate_id_is_a_conflict(client: httpx.AsyncClient, platform_admin_token: str) -> None:
    await client.post("/admin/v1/tenants", json={"tenantId": "dup", "name": "First"}, headers=_auth(platform_admin_token))

    resp = await client.post("/admin/v1/tenants", json={"tenantId": "dup", "name": "Second"}, headers=_auth(platform_admin_token))

    assert resp.status_code == 409


async def test_tenant_admin_cannot_create_a_tenant(client: httpx.AsyncClient, tenant_a_admin_token: str) -> None:
    resp = await client.post("/admin/v1/tenants", json={"name": "Nope"}, headers=_auth(tenant_a_admin_token))

    assert resp.status_code == 403


async def test_creating_a_tenant_without_a_token_is_unauthorized(client: httpx.AsyncClient) -> None:
    resp = await client.post("/admin/v1/tenants", json={"name": "Nope"})

    assert resp.status_code == 401


async def test_tenant_admin_can_read_their_own_tenant(client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str) -> None:
    resp = await client.get(f"/admin/v1/tenants/{tenant_a['tenantId']}", headers=_auth(tenant_a_admin_token))

    assert resp.status_code == 200
    assert resp.json()["tenantId"] == tenant_a["tenantId"]


async def test_tenant_admin_cannot_read_a_different_tenant(client: httpx.AsyncClient, tenant_b: dict, tenant_a_admin_token: str) -> None:
    resp = await client.get(f"/admin/v1/tenants/{tenant_b['tenantId']}", headers=_auth(tenant_a_admin_token))

    assert resp.status_code == 403


async def test_platform_admin_can_read_any_tenant(client: httpx.AsyncClient, tenant_a: dict, platform_admin_token: str) -> None:
    resp = await client.get(f"/admin/v1/tenants/{tenant_a['tenantId']}", headers=_auth(platform_admin_token))

    assert resp.status_code == 200


async def test_reading_an_unknown_tenant_is_404(client: httpx.AsyncClient, platform_admin_token: str) -> None:
    resp = await client.get("/admin/v1/tenants/no-such-tenant", headers=_auth(platform_admin_token))

    assert resp.status_code == 404


async def test_platform_admin_lists_tenants(client: httpx.AsyncClient, tenant_a: dict, tenant_b: dict, platform_admin_token: str) -> None:
    resp = await client.get("/admin/v1/tenants", headers=_auth(platform_admin_token))

    assert resp.status_code == 200
    ids = {t["tenantId"] for t in resp.json()}
    assert {tenant_a["tenantId"], tenant_b["tenantId"]} <= ids


async def test_tenant_admin_cannot_list_tenants(client: httpx.AsyncClient, tenant_a_admin_token: str) -> None:
    resp = await client.get("/admin/v1/tenants", headers=_auth(tenant_a_admin_token))

    assert resp.status_code == 403


async def test_platform_admin_deletes_a_tenant(client: httpx.AsyncClient, tenant_a: dict, platform_admin_token: str) -> None:
    resp = await client.delete(f"/admin/v1/tenants/{tenant_a['tenantId']}", headers=_auth(platform_admin_token))
    assert resp.status_code == 200

    again = await client.delete(f"/admin/v1/tenants/{tenant_a['tenantId']}", headers=_auth(platform_admin_token))
    assert again.status_code == 404


# ---- Target CRUD ------------------------------------------------------------


def _target_payload(**overrides) -> dict:
    payload = {"name": "web-01", "host": "10.0.0.5", "port": 443, "pluginRef": "tls-scanner", "pluginVersion": "2.1"}
    payload.update(overrides)
    return payload


async def test_tenant_admin_creates_a_target_in_their_own_tenant(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str
) -> None:
    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(), headers=_auth(tenant_a_admin_token)
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenantId"] == tenant_a["tenantId"]
    assert body["host"] == "10.0.0.5"
    assert body["credentialRef"] is None


async def test_tenant_admin_cannot_create_a_target_in_another_tenant(
    client: httpx.AsyncClient, tenant_b: dict, tenant_a_admin_token: str
) -> None:
    resp = await client.post(
        f"/admin/v1/tenants/{tenant_b['tenantId']}/targets", json=_target_payload(), headers=_auth(tenant_a_admin_token)
    )

    assert resp.status_code == 403


async def test_tenant_viewer_cannot_create_a_target(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_viewer_token: str
) -> None:
    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(), headers=_auth(tenant_a_viewer_token)
    )

    assert resp.status_code == 403


async def test_tenant_viewer_can_list_targets(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str, tenant_a_viewer_token: str
) -> None:
    await client.post(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(), headers=_auth(tenant_a_admin_token))

    resp = await client.get(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", headers=_auth(tenant_a_viewer_token))

    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_targets_are_isolated_per_tenant(
    client: httpx.AsyncClient, tenant_a: dict, tenant_b: dict, tenant_a_admin_token: str, tenant_b_admin_token: str
) -> None:
    await client.post(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(name="a-target"), headers=_auth(tenant_a_admin_token))
    await client.post(f"/admin/v1/tenants/{tenant_b['tenantId']}/targets", json=_target_payload(name="b-target"), headers=_auth(tenant_b_admin_token))

    resp = await client.get(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", headers=_auth(tenant_a_admin_token))

    names = [t["name"] for t in resp.json()]
    assert names == ["a-target"]


async def test_tenant_admin_cannot_read_another_tenants_target_even_by_id(
    client: httpx.AsyncClient, tenant_a: dict, tenant_b: dict, tenant_a_admin_token: str, tenant_b_admin_token: str
) -> None:
    created = await client.post(
        f"/admin/v1/tenants/{tenant_b['tenantId']}/targets", json=_target_payload(), headers=_auth(tenant_b_admin_token)
    )
    target_id = created.json()["targetId"]

    resp = await client.get(f"/admin/v1/tenants/{tenant_b['tenantId']}/targets/{target_id}", headers=_auth(tenant_a_admin_token))

    assert resp.status_code == 403


async def test_delete_target_then_get_is_404(client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str) -> None:
    created = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(), headers=_auth(tenant_a_admin_token)
    )
    target_id = created.json()["targetId"]

    delete_resp = await client.delete(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets/{target_id}", headers=_auth(tenant_a_admin_token))
    assert delete_resp.status_code == 200

    get_resp = await client.get(f"/admin/v1/tenants/{tenant_a['tenantId']}/targets/{target_id}", headers=_auth(tenant_a_admin_token))
    assert get_resp.status_code == 404


async def test_creating_a_target_with_a_duplicate_id_is_a_conflict(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str
) -> None:
    await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(targetId="dup-target"), headers=_auth(tenant_a_admin_token)
    )

    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets", json=_target_payload(targetId="dup-target"), headers=_auth(tenant_a_admin_token)
    )

    assert resp.status_code == 409


async def test_target_carries_credential_ref_pointer_not_a_secret(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str
) -> None:
    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/targets",
        json=_target_payload(credentialRef="site42-creds"),
        headers=_auth(tenant_a_admin_token),
    )

    assert resp.json()["credentialRef"] == "site42-creds"


# ---- Schedule CRUD ------------------------------------------------------------


async def _create_target(client: httpx.AsyncClient, tenant_id: str, token: str) -> str:
    resp = await client.post(f"/admin/v1/tenants/{tenant_id}/targets", json=_target_payload(), headers=_auth(token))
    return resp.json()["targetId"]


def _schedule_payload(target_id: str, **overrides) -> dict:
    payload = {"targetId": target_id, "jobType": "tls-scan", "manifestVersion": "1.0", "intervalSeconds": 3600}
    payload.update(overrides)
    return payload


async def test_tenant_admin_creates_a_schedule_for_their_own_target(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str
) -> None:
    target_id = await _create_target(client, tenant_a["tenantId"], tenant_a_admin_token)

    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules",
        json=_schedule_payload(target_id),
        headers=_auth(tenant_a_admin_token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["targetId"] == target_id
    assert body["intervalSeconds"] == 3600
    assert body["enabled"] is True
    assert body["nextRunAt"] is not None  # defaulted to "now" since omitted


async def test_creating_a_schedule_for_an_unknown_target_is_404(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str
) -> None:
    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules",
        json=_schedule_payload("no-such-target"),
        headers=_auth(tenant_a_admin_token),
    )

    assert resp.status_code == 404


async def test_creating_a_schedule_against_another_tenants_target_is_404(
    client: httpx.AsyncClient, tenant_a: dict, tenant_b: dict, tenant_a_admin_token: str, tenant_b_admin_token: str
) -> None:
    # target belongs to tenant B - tenant A must not be able to schedule
    # against it even by guessing/reusing its target_id.
    target_id = await _create_target(client, tenant_b["tenantId"], tenant_b_admin_token)

    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules",
        json=_schedule_payload(target_id),
        headers=_auth(tenant_a_admin_token),
    )

    assert resp.status_code == 404


async def test_creating_a_schedule_with_a_non_positive_interval_is_bad_request(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str
) -> None:
    target_id = await _create_target(client, tenant_a["tenantId"], tenant_a_admin_token)

    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules",
        json=_schedule_payload(target_id, intervalSeconds=0),
        headers=_auth(tenant_a_admin_token),
    )

    assert resp.status_code == 400


async def test_tenant_viewer_cannot_create_a_schedule(
    client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str, tenant_a_viewer_token: str
) -> None:
    target_id = await _create_target(client, tenant_a["tenantId"], tenant_a_admin_token)

    resp = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules",
        json=_schedule_payload(target_id),
        headers=_auth(tenant_a_viewer_token),
    )

    assert resp.status_code == 403


async def test_delete_schedule_then_get_is_404(client: httpx.AsyncClient, tenant_a: dict, tenant_a_admin_token: str) -> None:
    target_id = await _create_target(client, tenant_a["tenantId"], tenant_a_admin_token)
    created = await client.post(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules",
        json=_schedule_payload(target_id),
        headers=_auth(tenant_a_admin_token),
    )
    schedule_id = created.json()["scheduleId"]

    delete_resp = await client.delete(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules/{schedule_id}", headers=_auth(tenant_a_admin_token)
    )
    assert delete_resp.status_code == 200

    get_resp = await client.get(
        f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules/{schedule_id}", headers=_auth(tenant_a_admin_token)
    )
    assert get_resp.status_code == 404


async def test_schedules_are_isolated_per_tenant(
    client: httpx.AsyncClient, tenant_a: dict, tenant_b: dict, tenant_a_admin_token: str, tenant_b_admin_token: str
) -> None:
    target_a = await _create_target(client, tenant_a["tenantId"], tenant_a_admin_token)
    target_b = await _create_target(client, tenant_b["tenantId"], tenant_b_admin_token)
    await client.post(f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules", json=_schedule_payload(target_a), headers=_auth(tenant_a_admin_token))
    await client.post(f"/admin/v1/tenants/{tenant_b['tenantId']}/schedules", json=_schedule_payload(target_b), headers=_auth(tenant_b_admin_token))

    resp = await client.get(f"/admin/v1/tenants/{tenant_a['tenantId']}/schedules", headers=_auth(tenant_a_admin_token))

    assert len(resp.json()) == 1
    assert resp.json()[0]["targetId"] == target_a
