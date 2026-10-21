"""Per-tenant plugin version pinning: a tenant (customer) runs a pinned
version of each plugin; targets follow it unless they set their own
pluginVersion. Staged rollouts, change windows and one-step rollback."""

from __future__ import annotations

import pytest

from conftest import TEST_TARGET_ID, TEST_TENANT_ID, job_body
from saas_job_api.identity import AdminRole
from saas_job_api.orchestrator.scheduler_tick import run_scheduler_tick
from saas_job_api.tenancy import Schedule
from test_plugin_distribution_api import _token

PLUGINS = f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins"
TARGETS = f"/admin/v1/tenants/{TEST_TENANT_ID}/targets"


async def _publish(client, admin_headers, plugin: str, version: str) -> None:
    """Upload a release document, as the release pipeline does."""
    path = f"{plugin}/{version.replace('.', '').ljust(64, 'a')[:64]}.{version}.json"
    resp = await client.put(f"/admin/plugin-repo/targets/{path}", content=b'{"r":1}', headers=admin_headers)
    assert resp.status_code == 204


async def _pin(client, headers, version, plugin="tls-scanner", **extra):
    return await client.put(f"{PLUGINS}/{plugin}", json={"version": version, **extra}, headers=headers)


async def _job_version(app, client, admin_headers, target_id=TEST_TARGET_ID, tenant_id=TEST_TENANT_ID) -> str:
    resp = await client.post("/admin/jobs", json=job_body(tenantId=tenant_id, targetId=target_id), headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return (await app.state.store.get(resp.json()["jobId"])).payload["pluginVersion"]


@pytest.fixture
async def platform(app, client):
    return await _token(app, client, AdminRole.PLATFORM_ADMIN, None)


async def test_targets_without_a_version_follow_the_tenant_pin(app, client, admin_headers, platform) -> None:
    await _publish(client, admin_headers, "tls-scanner", "1.2")
    pinned = await _pin(client, platform, "1.2")
    assert pinned.status_code == 200
    assert pinned.json()["pinnedVersions"] == {"tls-scanner": "1.2"}

    created = await client.post(TARGETS, json={"targetId": "web-02", "name": "web-02", "host": "192.0.2.20",
                                               "port": 443, "pluginRef": "tls-scanner"}, headers=platform)
    assert created.status_code == 200, created.text
    assert created.json()["pluginVersion"] is None and created.json()["effectivePluginVersion"] == "1.2"
    assert await _job_version(app, client, admin_headers, "web-02") == "1.2"
    # The fixture target keeps its own explicit 1.0 (an override).
    assert await _job_version(app, client, admin_headers) == "1.0"


async def test_one_call_upgrades_or_rolls_back_a_whole_customer(app, client, admin_headers, platform) -> None:
    for version in ("1.2", "1.3"):
        await _publish(client, admin_headers, "tls-scanner", version)

    upgraded = await _pin(client, platform, "1.3", resetTargetOverrides=True)
    assert upgraded.status_code == 200
    assert await _job_version(app, client, admin_headers) == "1.3"   # override 1.0 cleared

    rolled_back = await _pin(client, platform, "1.2")
    assert rolled_back.status_code == 200
    assert await _job_version(app, client, admin_headers) == "1.2"

    target = (await client.get(f"{TARGETS}/{TEST_TARGET_ID}", headers=platform)).json()
    assert (target["pluginVersion"], target["effectivePluginVersion"]) == (None, "1.2")
    events = [e for e in await app.state.audit_store.list_recent(tenant_id=TEST_TENANT_ID)
              if e.event_type == "PLUGIN_VERSION_PINNED"]
    assert {(e.detail["previousVersion"], e.detail["version"]) for e in events} == {(None, "1.3"), ("1.3", "1.2")}


async def test_pins_are_per_tenant(app, client, admin_headers, platform) -> None:
    from conftest import seed_fixture_tenant_and_target

    await seed_fixture_tenant_and_target(app, tenant_id="tenant-other", target_id="other-target")
    await _publish(client, admin_headers, "tls-scanner", "1.3")
    await _pin(client, platform, "1.3", resetTargetOverrides=True)

    other = (await client.get("/admin/v1/tenants/tenant-other/plugins", headers=platform)).json()
    assert other["pinnedVersions"] == {"tls-scanner": None}
    # untouched by the first tenant's pin
    assert await _job_version(app, client, admin_headers, "other-target", "tenant-other") == "1.0"


async def test_only_published_versions_can_be_pinned(client, platform) -> None:
    resp = await _pin(client, platform, "9.9")
    assert resp.status_code == 400 and "not been published" in resp.text


@pytest.mark.parametrize("body", [{"version": "1.2;rm"}, {"version": "../1"}, {"version": "1.2", "extra": 1}])
async def test_malformed_pin_requests_are_rejected(client, platform, body) -> None:
    resp = await client.put(f"{PLUGINS}/tls-scanner", json=body, headers=platform)
    assert resp.status_code in (400, 422)


async def test_only_platform_admins_pin_versions(app, client, admin_headers) -> None:
    await _publish(client, admin_headers, "tls-scanner", "1.2")
    tenant_admin = await _token(app, client, AdminRole.TENANT_ADMIN, TEST_TENANT_ID)
    assert (await _pin(client, tenant_admin, "1.2")).status_code == 403


async def test_a_pin_cannot_be_removed_while_targets_follow_it(client, admin_headers, platform) -> None:
    await _publish(client, admin_headers, "tls-scanner", "1.2")
    await _pin(client, platform, "1.2", resetTargetOverrides=True)

    resp = await _pin(client, platform, None)
    assert resp.status_code == 409 and TEST_TARGET_ID in resp.text


async def test_without_override_or_pin_there_is_no_target_and_no_job(app, client, admin_headers, platform) -> None:
    resp = await client.post(TARGETS, json={"name": "x", "host": "192.0.2.30", "port": 443,
                                            "pluginRef": "tls-scanner"}, headers=platform)
    assert resp.status_code == 400 and "no pinned version" in resp.text


async def test_reset_needs_a_version(client, platform) -> None:
    resp = await client.put(f"{PLUGINS}/tls-scanner", json={"resetTargetOverrides": True}, headers=platform)
    assert resp.status_code == 400


async def test_scheduler_runs_the_pinned_version(app, client, admin_headers, platform) -> None:
    await _publish(client, admin_headers, "tls-scanner", "1.3")
    await _pin(client, platform, "1.3", resetTargetOverrides=True)
    now = app.state.clock.now()
    await app.state.schedule_store.create(Schedule(
        schedule_id="sched-pin", tenant_id=TEST_TENANT_ID, target_id=TEST_TARGET_ID, job_type="tls-scanner-scan",
        manifest_version="1.0", interval_seconds=86400, next_run_at=now, created_at=now,
    ))
    created = await run_scheduler_tick(schedule_store=app.state.schedule_store, target_store=app.state.target_store,
                                       job_store=app.state.store, clock=app.state.clock,
                                       plugin_store=app.state.plugin_store)
    assert created == 1
    assert (await app.state.store.list_all())[0].payload["pluginVersion"] == "1.3"


async def test_revoking_the_entitlement_drops_the_pin(app, client, admin_headers, platform) -> None:
    await _publish(client, admin_headers, "tls-scanner", "1.2")
    await _pin(client, platform, "1.2")
    await client.delete(f"{PLUGINS}/tls-scanner", headers=platform)
    regranted = await client.put(f"{PLUGINS}/tls-scanner", headers=platform)
    assert regranted.json()["pinnedVersions"] == {"tls-scanner": None}
