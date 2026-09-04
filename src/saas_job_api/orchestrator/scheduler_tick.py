"""Periodic function turning due Schedules into JobRecords (Phase 2.5).

Runs inside every render.yaml web instance (numInstances: 2) - there is no
separate worker process for this. Safe against double-firing because
ScheduleStoreBase.claim_due() does the actual claiming (SELECT ... FOR
UPDATE SKIP LOCKED for the Postgres adapter, confirmed 2026-09-04): only
one instance's claim_due() call ever returns a given due schedule per
tick, so run_scheduler_tick() itself doesn't need to know or care that
more than one instance might be calling it concurrently.
"""

from __future__ import annotations

import asyncio
import logging

from ..domain import JobRecord
from ..health import HealthState, derive_current_status
from ..health_store_base import HealthStoreBase
from ..schedule_store_base import ScheduleStoreBase
from ..store import new_correlation_id, new_job_id
from ..store_base import JobStoreBase
from ..target_store_base import TargetStoreBase
from ..time_provider import Clock

logger = logging.getLogger(__name__)

DEFAULT_TICK_INTERVAL_SECONDS = 30.0
DEFAULT_CLAIM_LIMIT = 100
DEFAULT_JOB_PRIORITY = 50
DEFAULT_JOB_MAX_ATTEMPTS = 8
DEFAULT_ORPHANED_JOB_SLA_SECONDS = 600.0
_HELD_STATUSES = (HealthState.UNREACHABLE, HealthState.FAILED)


async def run_scheduler_tick(
    *,
    schedule_store: ScheduleStoreBase,
    target_store: TargetStoreBase,
    job_store: JobStoreBase,
    clock: Clock,
    limit: int = DEFAULT_CLAIM_LIMIT,
) -> int:
    """Claim every currently-due schedule and create one JobRecord per
    claim, shaped to match the Gateway VM's own job-payload contract
    (Phase 2.3's parse_orchestrator_request(): pluginRef/pluginVersion/
    targetEndpoint/credentialRef). Pure - no sleep/looping, so it stays
    directly unit-testable; start_scheduler_loop() below is the looping
    wrapper. Returns the count of jobs actually created."""

    now = clock.now()
    due = await schedule_store.claim_due(now=now, limit=limit)
    created = 0

    for schedule in due:
        target = await target_store.get(schedule.tenant_id, schedule.target_id)
        if target is None:
            # The Target was deleted after the Schedule was created (no FK/
            # cascade between them - tenant_store.py's tables are otherwise
            # independent). The schedule was still claimed and its
            # next_run_at already advanced, so this just skips firing this
            # cycle rather than crashing the whole tick over one stale
            # schedule; it will be skipped again on every future tick until
            # someone deletes the schedule or re-creates the target.
            logger.warning(
                "scheduler_tick: schedule '%s' references missing target '%s' - skipped",
                schedule.schedule_id,
                schedule.target_id,
            )
            continue

        record = JobRecord(
            job_id=new_job_id(),
            job_type=schedule.job_type,
            manifest_version=schedule.manifest_version,
            priority=DEFAULT_JOB_PRIORITY,
            scheduled_at=now,
            correlation_id=new_correlation_id(),
            payload={
                "pluginRef": target.plugin_ref,
                "pluginVersion": target.plugin_version,
                "targetEndpoint": f"{target.host}:{target.port}",
                "credentialRef": target.credential_ref,
                "tenantId": schedule.tenant_id,
                "targetId": target.target_id,
                "scheduleId": schedule.schedule_id,
            },
            max_attempts=DEFAULT_JOB_MAX_ATTEMPTS,
            trace_id=None,
        )
        await job_store.seed(record)
        created += 1

    if due:
        logger.info(
            "scheduler_tick: claimed %d due schedule(s), created %d job(s)", len(due), created
        )
    return created


async def reissue_orphaned_jobs(
    *,
    job_store: JobStoreBase,
    health_store: HealthStoreBase,
    clock: Clock,
    sla_seconds: float = DEFAULT_ORPHANED_JOB_SLA_SECONDS,
    degraded_after_seconds: float,
    unreachable_after_seconds: float,
    failed_after_seconds: float,
) -> int:
    """Orphaned-job reissue: an ACKNOWLEDGED job whose owning gateway has
    decayed to UNREACHABLE/FAILED, and has sat that long since
    acknowledgement with no result, is reset to AVAILABLE so a
    replacement gateway (or the original, once healthy again) can pick it
    up - closing the gap the §24 new-assignment guard alone leaves open
    for a job already handed to a gateway that then gets wiped/replaced.
    Threshold kwargs mirror derive_current_status()'s own signature/
    Settings fields rather than taking a Settings object, for the same
    testability reason derive_current_status itself does."""

    now = clock.now()
    statuses = await health_store.list_all()
    unreachable_ids = {
        status.gateway_id
        for status in statuses
        if derive_current_status(
            status,
            now=now,
            degraded_after_seconds=degraded_after_seconds,
            unreachable_after_seconds=unreachable_after_seconds,
            failed_after_seconds=failed_after_seconds,
        )
        in _HELD_STATUSES
    }
    if not unreachable_ids:
        return 0

    reissued = await job_store.reissue_orphaned(now=now, unreachable_gateway_ids=unreachable_ids, sla_seconds=sla_seconds)
    if reissued:
        logger.warning(
            "scheduler_tick: reissued %d orphaned job(s) from unreachable gateway(s) %s",
            len(reissued),
            sorted(unreachable_ids),
        )
    return len(reissued)


async def start_scheduler_loop(
    *,
    schedule_store: ScheduleStoreBase,
    target_store: TargetStoreBase,
    job_store: JobStoreBase,
    health_store: HealthStoreBase,
    clock: Clock,
    shutdown_event: asyncio.Event,
    interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
    orphaned_job_sla_seconds: float = DEFAULT_ORPHANED_JOB_SLA_SECONDS,
    gateway_degraded_after_seconds: float = 90.0,
    gateway_unreachable_after_seconds: float = 300.0,
    gateway_failed_after_seconds: float = 1_800.0,
) -> None:
    """Ticks run_scheduler_tick() and reissue_orphaned_jobs() every
    interval_seconds until shutdown_event is set. Each step's failure is
    logged, not raised, and independent of the other - a transient DB
    error in one must not stop the other from running, this tick or any
    future one, for the remaining lifetime of the process."""

    while not shutdown_event.is_set():
        try:
            await run_scheduler_tick(
                schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock
            )
        except Exception:
            logger.exception("scheduler_tick: schedule tick failed")

        try:
            await reissue_orphaned_jobs(
                job_store=job_store,
                health_store=health_store,
                clock=clock,
                sla_seconds=orphaned_job_sla_seconds,
                degraded_after_seconds=gateway_degraded_after_seconds,
                unreachable_after_seconds=gateway_unreachable_after_seconds,
                failed_after_seconds=gateway_failed_after_seconds,
            )
        except Exception:
            logger.exception("scheduler_tick: orphaned-job reissue failed")

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
