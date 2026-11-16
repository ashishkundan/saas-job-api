"""Schedule creation: job type follows the target's plugin; minimum interval."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from saas_job_api.identity import AdminPrincipal, AdminRole
from saas_job_api.passwords import hash_password


@pytest.fixture
async def admin(app, client) -> dict[str, str]:
    await app.state.rbac_store.create_principal(AdminPrincipal(
        principal_id=str(uuid.uuid4()), username="sched-admin", password_hash=hash_password("pw"),
        role=AdminRole.PLATFORM_ADMIN, created_at=datetime.now(timezone.utc), tenant_id=None,
    ))
    resp = await client.post("/admin/v1/login", json={"username": "sched-admin", "password": "pw"})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


@pytest.fixture
async def target(client, admin) -> tuple[str, str]:
    tenant = (await client.post("/admin/v1/tenants", json={"name": "Sched"}, headers=admin)).json()["tenantId"]
    await client.put(f"/admin/v1/tenants/{tenant}/plugins/tls-scanner", headers=admin)
    resp = await client.post(f"/admin/v1/tenants/{tenant}/targets", headers=admin, json={
        "targetId": "web-443", "name": "web", "host": "10.0.0.5", "port": 443,
        "pluginRef": "tls-scanner", "pluginVersion": "1.0"})
    assert resp.status_code == 200, resp.text
    return tenant, "web-443"


async def test_job_type_defaults_to_the_targets_plugin(client, admin, target) -> None:
    tenant, target_id = target

    resp = await client.post(f"/admin/v1/tenants/{tenant}/schedules", headers=admin,
                             json={"targetId": target_id, "intervalSeconds": 900})

    assert resp.status_code == 200, resp.text
    assert resp.json()["jobType"] == "tls-scanner-scan"
    assert resp.json()["manifestVersion"] == "1.0"


async def test_job_type_that_does_not_match_the_plugin_is_rejected(client, admin, target) -> None:
    tenant, target_id = target

    resp = await client.post(f"/admin/v1/tenants/{tenant}/schedules", headers=admin,
                             json={"targetId": target_id, "jobType": "tls-scan", "intervalSeconds": 900})

    assert resp.status_code == 400
    assert "tls-scanner-scan" in resp.json()["detail"]
    assert (await client.get(f"/admin/v1/tenants/{tenant}/schedules", headers=admin)).json() == []


@pytest.mark.parametrize(("interval", "status"), [(299, 400), (300, 200)])
async def test_minimum_interval_is_five_minutes(client, admin, target, interval, status) -> None:
    tenant, target_id = target

    resp = await client.post(f"/admin/v1/tenants/{tenant}/schedules", headers=admin,
                             json={"targetId": target_id, "intervalSeconds": interval})

    assert resp.status_code == status, resp.text


async def _create(client, admin, tenant, target_id, **extra):
    resp = await client.post(f"/admin/v1/tenants/{tenant}/schedules", headers=admin,
                             json={"scheduleId": "s1", "targetId": target_id, "intervalSeconds": 900, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_patch_changes_interval_and_keeps_the_planned_next_run(client, admin, target) -> None:
    tenant, target_id = target
    created = await _create(client, admin, tenant, target_id, nextRunAt="2030-01-01T00:00:00Z")

    resp = await client.patch(f"/admin/v1/tenants/{tenant}/schedules/s1", headers=admin,
                              json={"intervalSeconds": 86400})

    assert resp.status_code == 200, resp.text
    assert resp.json()["intervalSeconds"] == 86400
    assert resp.json()["nextRunAt"] == created["nextRunAt"]
    assert (await client.get(f"/admin/v1/tenants/{tenant}/schedules/s1", headers=admin)).json()["intervalSeconds"] == 86400


async def test_patch_pauses_resumes_and_moves_the_next_run(client, admin, target) -> None:
    tenant, target_id = target
    await _create(client, admin, tenant, target_id)
    url = f"/admin/v1/tenants/{tenant}/schedules/s1"

    assert (await client.patch(url, headers=admin, json={"enabled": False})).json()["enabled"] is False
    resp = await client.patch(url, headers=admin, json={"enabled": True, "nextRunAt": "2030-06-01T02:00:00Z"})

    assert resp.json()["enabled"] is True
    assert resp.json()["nextRunAt"].startswith("2030-06-01T02:00:00")


@pytest.mark.parametrize("body", [
    {"intervalSeconds": 60},
    {},
    {"nextRunAt": "2030-06-01T02:00:00"},
    {"jobType": "other"},
])
async def test_patch_rejects_bad_bodies(client, admin, target, body) -> None:
    tenant, target_id = target
    await _create(client, admin, tenant, target_id)

    resp = await client.patch(f"/admin/v1/tenants/{tenant}/schedules/s1", headers=admin, json=body)

    assert resp.status_code in (400, 422), resp.text


async def test_patch_unknown_schedule_is_404(client, admin, target) -> None:
    tenant, _ = target

    resp = await client.patch(f"/admin/v1/tenants/{tenant}/schedules/nope", headers=admin, json={"enabled": False})

    assert resp.status_code == 404


async def test_patch_is_audited(app, client, admin, target) -> None:
    tenant, target_id = target
    await _create(client, admin, tenant, target_id)

    await client.patch(f"/admin/v1/tenants/{tenant}/schedules/s1", headers=admin, json={"enabled": False})

    events = [e for e in await app.state.audit_store.list_recent(tenant_id=tenant) if e.event_type == "SCHEDULE_UPDATED"]
    assert len(events) == 1 and events[0].detail == {"enabled": False}
