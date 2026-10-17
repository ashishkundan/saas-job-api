"""PostgresJobStore.claim() tenant scoping and job-type filtering against a
real database (runs in CI after `alembic upgrade head`)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import asyncpg
import pytest

from saas_job_api.domain import JobRecord
from saas_job_api.store_postgres import PostgresJobStore

_DATABASE_URL = os.environ.get("SAAS_JOB_API_TEST_DATABASE_URL")
_DATABASE_HOST = urlparse(_DATABASE_URL).hostname if _DATABASE_URL else None
pytestmark = pytest.mark.skipif(
    _DATABASE_HOST not in {"localhost", "127.0.0.1", "::1"},
    reason="requires an explicitly configured local PostgreSQL test database",
)


def _record(job_id: str, *, tenant_id: str | None, job_type: str = "tls-scanner-scan") -> JobRecord:
    return JobRecord(
        job_id=job_id,
        job_type=job_type,
        manifest_version="1.0",
        # Far above anything else in the shared test database, so these
        # rows are claimed first within their tenant.
        priority=10_000,
        scheduled_at=datetime.now(timezone.utc),
        correlation_id=f"corr-{job_id}",
        payload={"tenantId": tenant_id},
        max_attempts=8,
        trace_id=None,
        tenant_id=tenant_id,
        target_id="target-pg",
    )


@pytest.mark.asyncio
async def test_postgres_claim_is_scoped_to_the_gateways_tenant_and_job_types() -> None:
    if _DATABASE_URL is None:
        pytest.skip("local PostgreSQL test database is not configured")
    pool = await asyncpg.create_pool(_DATABASE_URL)
    store = PostgresJobStore(pool)
    suffix = uuid.uuid4().hex[:8]
    tenant_a, tenant_b = f"pg-a-{suffix}", f"pg-b-{suffix}"
    ids = {name: f"pg-{name}-{suffix}" for name in ("a_tls", "a_win", "b_tls", "legacy")}
    try:
        await store.seed(_record(ids["a_tls"], tenant_id=tenant_a))
        await store.seed(_record(ids["a_win"], tenant_id=tenant_a, job_type="windows-collector-scan"))
        await store.seed(_record(ids["b_tls"], tenant_id=tenant_b))
        await store.seed(_record(ids["legacy"], tenant_id=None))

        claimed = await store.claim(
            gateway_id="gw-pg-a",
            tenant_id=tenant_a,
            job_types=["tls-scanner-scan"],
            manifest_versions=["1.0"],
            max_jobs=10,
            dispatch_slots=None,
        )
        assert [j.job_id for j in claimed] == [ids["a_tls"]]
        assert claimed[0].tenant_id == tenant_a
        assert claimed[0].target_id == "target-pg"

        rest_a = await store.claim(
            gateway_id="gw-pg-a", tenant_id=tenant_a, job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
        )
        assert [j.job_id for j in rest_a] == [ids["a_win"]]

        assert (await store.get(ids["b_tls"])).reserved_by is None
        assert (await store.get(ids["legacy"])).reserved_by is None
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM jobs WHERE job_id = ANY($1)", list(ids.values()))
        await pool.close()
