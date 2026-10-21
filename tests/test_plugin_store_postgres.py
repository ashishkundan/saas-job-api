"""PostgresPluginStore against a real database (runs in CI after
`alembic upgrade head`, which includes migration 011)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import asyncpg
import pytest

from saas_job_api.plugin_store_postgres import PostgresPluginStore

_DATABASE_URL = os.environ.get("SAAS_JOB_API_TEST_DATABASE_URL")
_DATABASE_HOST = urlparse(_DATABASE_URL).hostname if _DATABASE_URL else None
pytestmark = pytest.mark.skipif(
    _DATABASE_HOST not in {"localhost", "127.0.0.1", "::1"},
    reason="requires an explicitly configured local PostgreSQL test database",
)


@pytest.mark.asyncio
async def test_postgres_plugin_store_round_trips_files_and_entitlements() -> None:
    if _DATABASE_URL is None:
        pytest.skip("local PostgreSQL test database is not configured")
    pool = await asyncpg.create_pool(_DATABASE_URL)
    store = PostgresPluginStore(pool)
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:8]
    tenant, path = f"pg-tenant-{suffix}", f"{suffix[:1]}9{suffix}.snapshot.json"
    try:
        await store.put_repo_file("metadata", path, b"first", now=now)
        await store.put_repo_file("metadata", path, b"second", now=now)  # replace in place
        assert await store.get_repo_file("metadata", path) == b"second"
        assert await store.get_repo_file("targets", path) is None

        assert await store.grant(tenant, "tls-scanner", now=now) is True
        assert await store.grant(tenant, "tls-scanner", now=now) is False
        assert await store.is_entitled(tenant, "tls-scanner") is True
        assert await store.list_plugins(tenant) == ["tls-scanner"]
        assert await store.revoke(tenant, "tls-scanner") is True
        assert await store.is_entitled(tenant, "tls-scanner") is False
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM plugin_repo_files WHERE path = $1", path)
            await conn.execute("DELETE FROM tenant_plugins WHERE tenant_id = $1", tenant)
        await pool.close()


@pytest.mark.asyncio
async def test_postgres_pins_versions_and_clears_target_overrides() -> None:
    """Migration 012: tenant_plugins.pinned_version, nullable targets.plugin_version."""
    if _DATABASE_URL is None:
        pytest.skip("local PostgreSQL test database is not configured")
    from saas_job_api.target_store_postgres import PostgresTargetStore
    from saas_job_api.tenancy import Target

    pool = await asyncpg.create_pool(_DATABASE_URL)
    store, targets = PostgresPluginStore(pool), PostgresTargetStore(pool)
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:8]
    tenant, plugin = f"pg-tenant-{suffix}", f"pg-plugin-{suffix}"
    release = f"{plugin}/" + "c" * 64 + ".1.3.json"
    try:
        await store.grant(tenant, plugin, now=now)
        assert await store.pinned_versions(tenant) == {plugin: None}
        assert await store.is_published(plugin, "1.3") is False
        await store.put_repo_file("targets", release, b"{}", now=now)
        assert await store.is_published(plugin, "1.3") is True
        assert await store.is_published(plugin, "1.") is False  # exact version, not a prefix

        assert await store.set_pinned_version(tenant, plugin, "1.3") is None
        assert await store.set_pinned_version(tenant, plugin, "1.2") == "1.3"
        assert await store.pinned_version(tenant, plugin) == "1.2"
        with pytest.raises(KeyError):
            await store.set_pinned_version(tenant, "not-entitled", "1.0")

        for i, version in enumerate(("1.0", None)):
            await targets.create(Target(target_id=f"pg-t{i}-{suffix}", tenant_id=tenant, name="t", host="192.0.2.1",
                                        port=443, plugin_ref=plugin, plugin_version=version, created_at=now))
        assert await targets.clear_version_overrides(tenant, plugin) == 1
        assert {t.plugin_version for t in await targets.list_by_tenant(tenant)} == {None}
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM targets WHERE tenant_id = $1", tenant)
            await conn.execute("DELETE FROM plugin_repo_files WHERE path = $1", release)
            await conn.execute("DELETE FROM tenant_plugins WHERE tenant_id = $1", tenant)
        await pool.close()
