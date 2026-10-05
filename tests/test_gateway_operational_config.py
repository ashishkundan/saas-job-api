from __future__ import annotations

from datetime import datetime, timezone

import pytest

from saas_job_api.identity import AdminRole
from saas_job_api.jwt_tokens import issue_token
from saas_job_api.tenancy import Tenant


def _admin_headers(app, role: AdminRole, tenant_id: str | None = None) -> dict[str, str]:
    token = issue_token(
        secret=app.state.settings.jwt_secret,
        subject=f"principal-{role.value}",
        role=role.value,
        ttl_seconds=3600,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_tenant(app, tenant_id: str) -> None:
    await app.state.tenant_store.create(
        Tenant(
            tenant_id=tenant_id,
            name=tenant_id,
            created_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_gateway_config_is_bound_to_bearer_identity_and_defaults(client, gateway_headers):
    response = await client.get("/gateway/v1/config", headers=gateway_headers)

    assert response.status_code == 200
    assert response.json() == {
        "schemaVersion": 1,
        "configVersion": 0,
        "pollIntervalMs": 2000,
        "heartbeatIntervalMs": 60000,
        "acceptNewJobs": True,
        "updatedAt": None,
    }
    assert (await client.get("/gateway/v1/config")).status_code == 401


@pytest.mark.asyncio
async def test_admin_config_is_tenant_scoped_and_audited(client, app):
    await _create_tenant(app, "tenant-a")
    await _create_tenant(app, "tenant-b")
    platform_headers = _admin_headers(app, AdminRole.PLATFORM_ADMIN)
    tenant_a_headers = _admin_headers(app, AdminRole.TENANT_ADMIN, "tenant-a")
    tenant_b_headers = _admin_headers(app, AdminRole.TENANT_ADMIN, "tenant-b")
    path_a = "/admin/v1/tenants/tenant-a/gateways/gw_test/config"
    path_b = "/admin/v1/tenants/tenant-b/gateways/gw_test/config"

    created = await client.put(
        path_a,
        headers=platform_headers,
        json={"pollIntervalMs": 17000, "heartbeatIntervalMs": 45000, "acceptNewJobs": False},
    )
    assert created.status_code == 200
    assert created.json()["configVersion"] == 1

    updated = await client.put(
        path_a,
        headers=tenant_a_headers,
        json={"pollIntervalMs": 9000, "heartbeatIntervalMs": 30000, "acceptNewJobs": True},
    )
    assert updated.status_code == 200
    assert updated.json()["configVersion"] == 2

    assert (await client.get(path_a, headers=tenant_b_headers)).status_code == 403
    assert (
        await client.put(
            path_b,
            headers=tenant_b_headers,
            json={"pollIntervalMs": 9000, "heartbeatIntervalMs": 30000, "acceptNewJobs": True},
        )
    ).status_code == 404
    assert (await client.get("/gateway/v1/config", headers={"Authorization": "Bearer test-gateway-token"})).json()[
        "configVersion"
    ] == 2

    events = await app.state.audit_store.list_recent(tenant_id="tenant-a")
    assert len(events) == 2
    assert {event.event_type for event in events} == {"GATEWAY_OPERATIONAL_CONFIG_UPDATED"}
    assert {event.resource_id for event in events} == {"gw_test"}
    assert {event.detail["current"]["pollIntervalMs"] for event in events} == {9000, 17000}


@pytest.mark.asyncio
async def test_disabled_config_holds_new_poll_claims_and_poll_interval_is_returned(
    client,
    app,
    admin_headers,
    gateway_headers,
):
    await _create_tenant(app, "tenant-a")
    platform_headers = _admin_headers(app, AdminRole.PLATFORM_ADMIN)
    path = "/admin/v1/tenants/tenant-a/gateways/gw_test/config"
    seed = await client.post(
        "/admin/jobs",
        headers=admin_headers,
        json={"jobId": "job-config-pause", "jobType": "tls", "manifestVersion": "1.0"},
    )
    assert seed.status_code == 200

    paused = await client.put(
        path,
        headers=platform_headers,
        json={"pollIntervalMs": 17000, "heartbeatIntervalMs": 45000, "acceptNewJobs": False},
    )
    assert paused.status_code == 200
    held = await client.post("/gateway/v1/jobs/poll", headers=gateway_headers, json={"maxJobs": 1})
    assert held.status_code == 204
    records = await app.state.store.list_all()
    assert records[0].state.value == "AVAILABLE"

    await client.put(
        path,
        headers=platform_headers,
        json={"pollIntervalMs": 17000, "heartbeatIntervalMs": 45000, "acceptNewJobs": True},
    )
    delivered = await client.post("/gateway/v1/jobs/poll", headers=gateway_headers, json={"maxJobs": 1})
    assert delivered.status_code == 200
    assert delivered.json()["pollAfterMs"] == 17000
    assert [job["jobId"] for job in delivered.json()["jobs"]] == ["job-config-pause"]


@pytest.mark.asyncio
async def test_config_rejects_out_of_bounds_intervals(client, app):
    await _create_tenant(app, "tenant-a")
    response = await client.put(
        "/admin/v1/tenants/tenant-a/gateways/gw_test/config",
        headers=_admin_headers(app, AdminRole.PLATFORM_ADMIN),
        json={"pollIntervalMs": 499, "heartbeatIntervalMs": 45000, "acceptNewJobs": True},
    )
    assert response.status_code == 400
    assert await app.state.gateway_operational_config_store.get("gw_test") is None
