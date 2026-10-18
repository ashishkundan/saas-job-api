"""Plugin distribution in the SaaS: serving the signed repository (untrusted
transport) and per-tenant plugin entitlements."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from conftest import TEST_TARGET_ID, TEST_TENANT_ID, job_body
from saas_job_api.identity import AdminPrincipal, AdminRole
from saas_job_api.orchestrator.scheduler_tick import run_scheduler_tick
from saas_job_api.passwords import hash_password
from saas_job_api.tenancy import Schedule

META = "/gateway/v1/plugin-repo/metadata"
TARGETS = "/gateway/v1/plugin-repo/targets"
TARGET_FILE = "tls-scanner/" + "a" * 64 + ".1.0.json"


async def _token(app, client, role: AdminRole, tenant_id: str | None) -> dict[str, str]:
    name = f"{role.value}-{uuid.uuid4().hex[:6]}"
    await app.state.rbac_store.create_principal(AdminPrincipal(
        principal_id=str(uuid.uuid4()), username=name, password_hash=hash_password("pw-" + name),
        role=role, created_at=datetime.now(timezone.utc), tenant_id=tenant_id,
    ))
    resp = await client.post("/admin/v1/login", json={"username": name, "password": "pw-" + name})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


# ------------------------------------------------------------ repository


async def test_gateways_read_uploaded_repository_files_verbatim(client, admin_headers, gateway_headers) -> None:
    body = b'{"signed": {"_type": "timestamp"}, "signatures": []}'
    put = await client.put("/admin/plugin-repo/metadata/timestamp.json", content=body, headers=admin_headers)
    assert put.status_code == 204
    await client.put(f"/admin/plugin-repo/targets/{TARGET_FILE}", content=b'{"x":1}', headers=admin_headers)

    meta = await client.get(f"{META}/timestamp.json", headers=gateway_headers)
    target = await client.get(f"{TARGETS}/{TARGET_FILE}", headers=gateway_headers)

    assert meta.status_code == 200 and meta.content == body
    assert meta.headers["cache-control"] == "no-store"
    assert target.status_code == 200 and target.content == b'{"x":1}'


async def test_repository_reads_require_a_gateway_token(client, admin_headers) -> None:
    await client.put("/admin/plugin-repo/metadata/timestamp.json", content=b"{}", headers=admin_headers)
    assert (await client.get(f"{META}/timestamp.json")).status_code == 401
    assert (await client.get(f"{META}/timestamp.json", headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_repository_uploads_require_the_admin_token(client, gateway_headers) -> None:
    resp = await client.put("/admin/plugin-repo/metadata/timestamp.json", content=b"{}", headers=gateway_headers)
    assert resp.status_code == 401


@pytest.mark.parametrize("kind,path", [
    ("metadata", "root.json"),               # only versioned roots are served
    ("metadata", "1.root.json.bak"),
    ("metadata", "../etc/passwd"),
    ("targets", "tls-scanner/1.0.json"),     # consistent-snapshot names only
    ("targets", "../../secret.json"),
    ("other", "timestamp.json"),
])
async def test_only_tuf_repository_paths_are_accepted(client, admin_headers, kind, path) -> None:
    resp = await client.put(f"/admin/plugin-repo/{kind}/{path}", content=b"{}", headers=admin_headers)
    assert resp.status_code in (400, 404)


async def test_oversized_or_empty_repository_files_are_refused(client, admin_headers) -> None:
    assert (await client.put("/admin/plugin-repo/metadata/timestamp.json", content=b"", headers=admin_headers)).status_code == 400
    big = b"x" * (1024 * 1024 + 1)
    assert (await client.put("/admin/plugin-repo/metadata/timestamp.json", content=big, headers=admin_headers)).status_code == 400


async def test_unknown_repository_file_is_404(client, gateway_headers) -> None:
    assert (await client.get(f"{META}/7.snapshot.json", headers=gateway_headers)).status_code == 404


# --------------------------------------------------------- entitlements


async def test_platform_admin_grants_lists_and_revokes_entitlements(app, client) -> None:
    platform = await _token(app, client, AdminRole.PLATFORM_ADMIN, None)

    granted = await client.put(f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins/windows-collector", headers=platform)
    assert granted.status_code == 200
    assert granted.json()["plugins"] == ["tls-scanner", "windows-collector"]

    revoked = await client.delete(f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins/windows-collector", headers=platform)
    assert revoked.json()["plugins"] == ["tls-scanner"]
    assert (await client.delete(f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins/windows-collector", headers=platform)).status_code == 404

    events = [e.event_type for e in await app.state.audit_store.list_recent(tenant_id=TEST_TENANT_ID)]
    assert "PLUGIN_ENTITLEMENT_GRANTED" in events and "PLUGIN_ENTITLEMENT_REVOKED" in events


async def test_tenant_admin_can_list_but_not_grant(app, client) -> None:
    tenant_admin = await _token(app, client, AdminRole.TENANT_ADMIN, TEST_TENANT_ID)

    listed = await client.get(f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins", headers=tenant_admin)
    assert listed.json()["plugins"] == ["tls-scanner"]
    assert (await client.put(f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins/windows-collector", headers=tenant_admin)).status_code == 403


async def test_granting_for_an_unknown_tenant_or_bad_plugin_id_fails(app, client) -> None:
    platform = await _token(app, client, AdminRole.PLATFORM_ADMIN, None)
    assert (await client.put("/admin/v1/tenants/tenant-nope/plugins/tls-scanner", headers=platform)).status_code == 404
    assert (await client.put(f"/admin/v1/tenants/{TEST_TENANT_ID}/plugins/Bad_Id", headers=platform)).status_code == 400


async def test_a_target_for_an_unentitled_plugin_is_refused(app, client) -> None:
    tenant_admin = await _token(app, client, AdminRole.TENANT_ADMIN, TEST_TENANT_ID)
    resp = await client.post(
        f"/admin/v1/tenants/{TEST_TENANT_ID}/targets",
        json={"name": "dc-01", "host": "10.0.0.9", "port": 5985, "pluginRef": "windows-collector", "pluginVersion": "1.0"},
        headers=tenant_admin,
    )
    assert resp.status_code == 400
    assert "not entitled" in resp.text


async def test_jobs_stop_once_the_entitlement_is_revoked(app, client, admin_headers) -> None:
    assert (await client.post("/admin/jobs", json=job_body(), headers=admin_headers)).status_code == 200
    await app.state.plugin_store.revoke(TEST_TENANT_ID, "tls-scanner")

    resp = await client.post("/admin/jobs", json=job_body(), headers=admin_headers)
    assert resp.status_code == 400
    assert "not entitled" in resp.text


async def test_scheduler_skips_unentitled_plugins_and_adds_the_schedule_interval(app) -> None:
    now = app.state.clock.now()
    await app.state.schedule_store.create(Schedule(
        schedule_id="sched-weekly", tenant_id=TEST_TENANT_ID, target_id=TEST_TARGET_ID,
        job_type="tls-scanner-scan", manifest_version="1.0", interval_seconds=7 * 86400,
        next_run_at=now, created_at=now,
    ))
    tick = dict(schedule_store=app.state.schedule_store, target_store=app.state.target_store,
                job_store=app.state.store, clock=app.state.clock, plugin_store=app.state.plugin_store)

    assert await run_scheduler_tick(**tick) == 1
    job = (await app.state.store.list_all())[0]
    assert job.payload["scheduleIntervalSeconds"] == 7 * 86400  # gateway grace period for a weekly job

    await app.state.plugin_store.revoke(TEST_TENANT_ID, "tls-scanner")
    app.state.clock.advance(7 * 86400 + 1)
    assert await run_scheduler_tick(**tick) == 0
