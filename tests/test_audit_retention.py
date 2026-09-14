"""audit_events retention (Phase 2.7): AuditLogStoreBase.purge_expired()
and AuditRetentionSweeper - pure unit tests against MemoryAuditLogStore,
no HTTP layer needed."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from saas_job_api.audit import AuditEvent
from saas_job_api.audit_retention import AuditRetentionSweeper
from saas_job_api.audit_store_memory import MemoryAuditLogStore
from saas_job_api.time_provider import FakeClock

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
SEVEN_YEARS_DAYS = 2555


def _event(event_id: str, *, occurred_at: datetime) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        event_type="TENANT_CREATED",
        actor="someone",
        tenant_id=None,
        resource_type=None,
        resource_id=None,
        detail={},
        occurred_at=occurred_at,
    )


async def test_purge_expired_deletes_only_rows_older_than_the_cutoff() -> None:
    store = MemoryAuditLogStore()
    old = _event("old", occurred_at=NOW - timedelta(days=SEVEN_YEARS_DAYS + 1))
    recent = _event("recent", occurred_at=NOW - timedelta(days=SEVEN_YEARS_DAYS - 1))
    await store.append(old)
    await store.append(recent)

    deleted = await store.purge_expired(before=NOW - timedelta(days=SEVEN_YEARS_DAYS), limit=100)

    assert deleted == 1
    remaining = await store.list_recent(limit=100)
    assert [e.event_id for e in remaining] == ["recent"]


async def test_purge_expired_respects_the_batch_limit() -> None:
    store = MemoryAuditLogStore()
    for i in range(5):
        await store.append(_event(f"old-{i}", occurred_at=NOW - timedelta(days=SEVEN_YEARS_DAYS + 1)))

    deleted = await store.purge_expired(before=NOW - timedelta(days=SEVEN_YEARS_DAYS), limit=3)

    assert deleted == 3
    remaining = await store.list_recent(limit=100)
    assert len(remaining) == 2


async def test_purge_expired_is_a_no_op_when_nothing_is_past_the_floor() -> None:
    store = MemoryAuditLogStore()
    await store.append(_event("recent", occurred_at=NOW))

    deleted = await store.purge_expired(before=NOW - timedelta(days=SEVEN_YEARS_DAYS), limit=100)

    assert deleted == 0
    assert len(await store.list_recent(limit=100)) == 1


async def test_sweep_once_uses_the_configured_retention_floor() -> None:
    store = MemoryAuditLogStore()
    await store.append(_event("just-inside-floor", occurred_at=NOW - timedelta(days=SEVEN_YEARS_DAYS - 1)))
    await store.append(_event("past-floor", occurred_at=NOW - timedelta(days=SEVEN_YEARS_DAYS + 1)))
    clock = FakeClock(NOW)
    sweeper = AuditRetentionSweeper(store=store, clock=clock, retention_days=SEVEN_YEARS_DAYS, batch_size=100)

    deleted = await sweeper.sweep_once()

    assert deleted == 1
    remaining = await store.list_recent(limit=100)
    assert [e.event_id for e in remaining] == ["just-inside-floor"]


async def test_run_sweeps_repeatedly_and_stops_on_shutdown() -> None:
    store = MemoryAuditLogStore()
    await store.append(_event("past-floor", occurred_at=NOW - timedelta(days=SEVEN_YEARS_DAYS + 1)))
    clock = FakeClock(NOW)
    shutdown_event = asyncio.Event()
    sweeper = AuditRetentionSweeper(
        store=store, clock=clock, retention_days=SEVEN_YEARS_DAYS, batch_size=100, interval_seconds=0.03
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        shutdown_event.set()

    stopper = asyncio.create_task(_stop_soon())
    await asyncio.wait_for(sweeper.run(shutdown_event), timeout=2.0)
    await stopper

    assert await store.list_recent(limit=100) == []
