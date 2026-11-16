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
