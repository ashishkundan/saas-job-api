from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import asyncpg
import pytest

from saas_job_api.audit import AuditEvent
from saas_job_api.audit_store_postgres import PostgresAuditLogStore
from saas_job_api.gateway_operational_config_store_postgres import PostgresGatewayOperationalConfigStore
from saas_job_api.store_postgres import PostgresJobStore
from saas_job_api.domain import JobState

_DATABASE_URL = os.environ.get("SAAS_JOB_API_TEST_DATABASE_URL")
_DATABASE_HOST = urlparse(_DATABASE_URL).hostname if _DATABASE_URL else None
pytestmark = pytest.mark.skipif(
    _DATABASE_HOST not in {"localhost", "127.0.0.1", "::1"},
    reason="requires an explicitly configured local PostgreSQL test database",
)


@pytest.mark.asyncio
async def test_postgres_gateway_config_serializes_versions_and_tenant_binding(monkeypatch) -> None:
    if _DATABASE_URL is None:
        pytest.skip("local PostgreSQL test database is not configured")
    pool = await asyncpg.create_pool(_DATABASE_URL)
    gateway_id = f"test-{uuid.uuid4()}"
    failed_gateway_id = f"test-audit-failure-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    store = PostgresGatewayOperationalConfigStore(pool)
    audit_store = PostgresAuditLogStore(pool)

    def make_audit_event(previous, current) -> AuditEvent:
        return AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type="GATEWAY_OPERATIONAL_CONFIG_UPDATED",
            actor="postgres-test",
            tenant_id="tenant-postgres-test",
            resource_type="gateway_config",
            resource_id=current.gateway_id,
            detail={
                "previousVersion": previous.config_version if previous else None,
                "currentVersion": current.config_version,
            },
            occurred_at=current.updated_at,
        )

    try:
        results = await asyncio.gather(
            *(
                store.save_with_previous(
                    gateway_id=gateway_id,
                    tenant_id="tenant-postgres-test",
                    poll_interval_ms=poll_interval_ms,
                    heartbeat_interval_ms=30_000,
                    accept_new_jobs=True,
                    updated_at=now,
                    audit_store=audit_store,
                    audit_event_factory=make_audit_event,
                )
                for poll_interval_ms in (2_000, 3_000, 4_000)
            )
        )

        by_version = {current.config_version: previous for previous, current in results}
        assert set(by_version) == {1, 2, 3}
        assert by_version[1] is None
        assert by_version[2] is not None and by_version[2].config_version == 1
        assert by_version[3] is not None and by_version[3].config_version == 2
        events = await audit_store.list_recent(tenant_id="tenant-postgres-test", limit=20)
        matching_events = [event for event in events if event.resource_id == gateway_id]
        by_event_version = {event.detail["currentVersion"]: event for event in matching_events}
        assert set(by_event_version) == {1, 2, 3}
        assert by_event_version[2].detail["previousVersion"] == 1
        assert by_event_version[3].detail["previousVersion"] == 2

        with pytest.raises(ValueError, match="tenant"):
            await store.save_with_previous(
                gateway_id=gateway_id,
                tenant_id="another-tenant",
                poll_interval_ms=5_000,
                heartbeat_interval_ms=30_000,
                accept_new_jobs=True,
                updated_at=now,
            )

        async def fail_audit_append(connection, event) -> None:
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(audit_store, "append_with_connection", fail_audit_append)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            await store.save_with_previous(
                gateway_id=failed_gateway_id,
                tenant_id="tenant-postgres-test",
                poll_interval_ms=2_000,
                heartbeat_interval_ms=30_000,
                accept_new_jobs=True,
                updated_at=now,
                audit_store=audit_store,
                audit_event_factory=make_audit_event,
            )
        assert await store.get(failed_gateway_id) is None
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM audit_events WHERE resource_id = ANY($1::text[])",
                [gateway_id, failed_gateway_id],
            )
            await conn.execute(
                "DELETE FROM gateway_operational_configs WHERE gateway_id = ANY($1::text[])",
                [gateway_id, failed_gateway_id],
            )
        await pool.close()


@pytest.mark.asyncio
async def test_postgres_interruption_receipt_survives_restart_and_concurrent_replay() -> None:
    assert _DATABASE_URL is not None
    pool = await asyncpg.create_pool(_DATABASE_URL)
    job_id = f"test-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO jobs (job_id, job_type, manifest_version, payload, correlation_id, scheduled_at, "
                "state, ack_gateway_id) VALUES ($1, 'TLS_SCAN', '1.0', '{}', $1, $2, 'ACKNOWLEDGED', 'test-gw')",
                job_id, now,
            )
        store = PostgresJobStore(pool)
        results = await asyncio.gather(*(
            store.reissue_one(job_id=job_id, gateway_id="test-gw", attempt_token="attempt-1", now=now)
            for _ in range(3)
        ))
        assert sum(result is not None for result in results) == 1
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE jobs SET state = 'ACKNOWLEDGED', ack_gateway_id = 'test-gw' WHERE job_id = $1", job_id,
            )
        restarted = PostgresJobStore(pool)
        assert await restarted.reissue_one(
            job_id=job_id, gateway_id="test-gw", attempt_token="attempt-1", now=now,
        ) is None
        assert (await restarted.get(job_id)).state == JobState.ACKNOWLEDGED
        assert await restarted.reissue_one(
            job_id=job_id, gateway_id="wrong-gw", attempt_token="attempt-2", now=now,
        ) is None
        assert await restarted.reissue_one(
            job_id=job_id, gateway_id="test-gw", attempt_token="attempt-2", now=now,
        ) is not None
        async with pool.acquire() as conn:
            assert await conn.fetchval(
                "SELECT COUNT(*) FROM job_interruption_receipts WHERE job_id = $1", job_id,
            ) == 2
            await conn.execute("DELETE FROM jobs WHERE job_id = $1", job_id)
            assert await conn.fetchval(
                "SELECT COUNT(*) FROM job_interruption_receipts WHERE job_id = $1", job_id,
            ) == 0
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM jobs WHERE job_id = $1", job_id)
        await pool.close()
