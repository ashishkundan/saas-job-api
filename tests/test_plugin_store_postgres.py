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
