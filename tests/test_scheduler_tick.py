"""run_scheduler_tick() / claim_due() (Phase 2.5) - pure unit tests against
the in-memory stores directly, no HTTP layer needed."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from saas_job_api.domain import JobRecord, JobState
from saas_job_api.health import GatewayStatus, HealthState
from saas_job_api.health_store_memory import MemoryHealthStore
from saas_job_api.orchestrator.scheduler_tick import reissue_orphaned_jobs, run_scheduler_tick, start_scheduler_loop
from saas_job_api.schedule_store_memory import MemoryScheduleStore
from saas_job_api.store_memory import MemoryJobStore
from saas_job_api.target_store_memory import MemoryTargetStore
from saas_job_api.tenancy import Schedule, Target
from saas_job_api.time_provider import FakeClock

# health.py's derive_current_status thresholds, used verbatim by the
# reissue_orphaned_jobs tests below.
DEGRADED_AFTER = 90.0
UNREACHABLE_AFTER = 300.0
FAILED_AFTER = 1_800.0

NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


def _target(**overrides) -> Target:
    defaults = dict(
        target_id="target-1",
        tenant_id="tenant-1",
        name="web-01",
        host="10.0.0.5",
        port=443,
        plugin_ref="tls-scanner",
        plugin_version="2.1",
        created_at=NOW,
        credential_ref="site42-creds",
    )
    defaults.update(overrides)
    return Target(**defaults)


def _schedule(**overrides) -> Schedule:
    defaults = dict(
        schedule_id="sched-1",
        tenant_id="tenant-1",
        target_id="target-1",
        job_type="tls-scan",
        manifest_version="1.0",
        interval_seconds=3600,
        next_run_at=NOW,
        created_at=NOW,
    )
    defaults.update(overrides)
    return Schedule(**defaults)


async def _stores():
    schedule_store = MemoryScheduleStore()
    target_store = MemoryTargetStore()
    job_store = MemoryJobStore(clock=FakeClock(NOW))
    await target_store.create(_target())
    return schedule_store, target_store, job_store


async def test_run_scheduler_tick_creates_a_job_for_a_due_schedule() -> None:
    schedule_store, target_store, job_store = await _stores()
    await schedule_store.create(_schedule())
    clock = FakeClock(NOW)

    created = await run_scheduler_tick(schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock)

    assert created == 1
    jobs = await job_store.list_all()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.job_type == "tls-scan"
    assert job.manifest_version == "1.0"
    assert job.payload["pluginRef"] == "tls-scanner"
    assert job.payload["pluginVersion"] == "2.1"
    assert job.payload["targetEndpoint"] == "10.0.0.5:443"
    assert job.payload["credentialRef"] == "site42-creds"
    assert job.payload["scheduleId"] == "sched-1"


async def test_run_scheduler_tick_skips_a_schedule_not_yet_due() -> None:
    schedule_store, target_store, job_store = await _stores()
    await schedule_store.create(_schedule(next_run_at=NOW + timedelta(hours=1)))
    clock = FakeClock(NOW)

    created = await run_scheduler_tick(schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock)

    assert created == 0
    assert await job_store.list_all() == []


async def test_run_scheduler_tick_skips_a_disabled_schedule() -> None:
    schedule_store, target_store, job_store = await _stores()
    await schedule_store.create(_schedule(enabled=False))
    clock = FakeClock(NOW)

    created = await run_scheduler_tick(schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock)

    assert created == 0


async def test_run_scheduler_tick_advances_next_run_at_and_sets_last_run_at() -> None:
    schedule_store, target_store, job_store = await _stores()
    await schedule_store.create(_schedule(interval_seconds=3600))
    clock = FakeClock(NOW)

    await run_scheduler_tick(schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock)

    updated = await schedule_store.get("tenant-1", "sched-1")
    assert updated.next_run_at == NOW + timedelta(seconds=3600)
    assert updated.last_run_at == NOW


async def test_run_scheduler_tick_skips_a_schedule_whose_target_was_deleted_but_still_advances_it() -> None:
    schedule_store, target_store, job_store = await _stores()
    await schedule_store.create(_schedule())
    await target_store.delete("tenant-1", "target-1")
    clock = FakeClock(NOW)

    created = await run_scheduler_tick(schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock)

    assert created == 0
    assert await job_store.list_all() == []
    # still claimed and advanced - a permanently-dangling schedule doesn't
    # retry every tick forever at the same next_run_at.
    updated = await schedule_store.get("tenant-1", "sched-1")
    assert updated.next_run_at > NOW


async def test_run_scheduler_tick_processes_multiple_due_schedules_independently() -> None:
    schedule_store, target_store, job_store = await _stores()
    await target_store.create(_target(target_id="target-2", name="web-02"))
    await schedule_store.create(_schedule(schedule_id="sched-1", target_id="target-1"))
    await schedule_store.create(_schedule(schedule_id="sched-2", target_id="target-2"))
    clock = FakeClock(NOW)

    created = await run_scheduler_tick(schedule_store=schedule_store, target_store=target_store, job_store=job_store, clock=clock)

    assert created == 2


async def test_claim_due_does_not_reclaim_a_schedule_it_just_advanced() -> None:
    """The core double-fire-prevention property: a second claim_due() call
    at the same `now` must not see the schedule this call already claimed
    and advanced past next_run_at - this is what makes it safe for both
    render.yaml web instances to run the same tick loop concurrently."""
    schedule_store, _target_store, _job_store = await _stores()
    await schedule_store.create(_schedule())

    first = await schedule_store.claim_due(now=NOW, limit=10)
    second = await schedule_store.claim_due(now=NOW, limit=10)

    assert len(first) == 1
    assert second == []


async def test_claim_due_respects_the_limit() -> None:
    schedule_store, _target_store, _job_store = await _stores()
    for i in range(5):
        await schedule_store.create(_schedule(schedule_id=f"sched-{i}"))

    claimed = await schedule_store.claim_due(now=NOW, limit=3)

    assert len(claimed) == 3


async def test_start_scheduler_loop_ticks_repeatedly_and_stops_on_shutdown() -> None:
    schedule_store, target_store, job_store = await _stores()
    await schedule_store.create(_schedule(interval_seconds=1))
    health_store = MemoryHealthStore()
    clock = FakeClock(NOW)
    shutdown_event = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.12)
        shutdown_event.set()

    stopper = asyncio.create_task(_stop_soon())
    await asyncio.wait_for(
        start_scheduler_loop(
            schedule_store=schedule_store,
            target_store=target_store,
            job_store=job_store,
            health_store=health_store,
            clock=clock,
            shutdown_event=shutdown_event,
            interval_seconds=0.03,
        ),
        timeout=2.0,
    )
    await stopper

    # The very first (immediate, pre-sleep) tick must have fired at least.
    assert len(await job_store.list_all()) >= 1


# ---- Orphaned-job reissue --------------------------------------------------


async def _seeded_and_acknowledged_job(job_store: MemoryJobStore, *, gateway_id: str, ack_received_at: datetime) -> JobRecord:
    record = JobRecord(
        job_id="job-1",
        job_type="tls-scan",
        manifest_version="1.0",
        priority=50,
        scheduled_at=NOW,
        correlation_id="corr-1",
        payload={},
        max_attempts=8,
        trace_id=None,
    )
    await job_store.seed(record)
    claimed = await job_store.claim(gateway_id=gateway_id, job_types=None, manifest_versions=None, max_jobs=1, dispatch_slots=None)
    job = claimed[0]
    return await job_store.acknowledge(
        job_id=job.job_id,
        gateway_id=gateway_id,
        receipt_token=job.receipt_token,
        received_at=ack_received_at,
        payload_hash=None,
        local_record_version=None,
    )


async def test_reissue_orphaned_jobs_resets_a_job_from_an_unreachable_gateway_past_the_sla() -> None:
    job_store = MemoryJobStore(clock=FakeClock(NOW))
    health_store = MemoryHealthStore()
    await _seeded_and_acknowledged_job(job_store, gateway_id="gw-1", ack_received_at=NOW - timedelta(seconds=700))
    await health_store.upsert(
        GatewayStatus(
            gateway_id="gw-1", tenant_id=None, last_heartbeat_at=NOW - timedelta(seconds=400),
            gateway_version="1.0", container_runtime_status="DOWN", last_successful_job_at=None, last_error=None,
        )
    )
    clock = FakeClock(NOW)

    reissued = await reissue_orphaned_jobs(
        job_store=job_store, health_store=health_store, clock=clock, sla_seconds=600.0,
        degraded_after_seconds=DEGRADED_AFTER, unreachable_after_seconds=UNREACHABLE_AFTER, failed_after_seconds=FAILED_AFTER,
    )

    assert reissued == 1
    job = (await job_store.list_all())[0]
    assert job.state == JobState.AVAILABLE
    assert job.ack_gateway_id is None
    assert job.reserved_by is None
    assert job.receipt_token is None


async def test_reissue_orphaned_jobs_leaves_a_recently_acknowledged_job_alone() -> None:
    job_store = MemoryJobStore(clock=FakeClock(NOW))
    health_store = MemoryHealthStore()
    # gateway is unreachable, but the job was only just acknowledged -
    # still within the SLA grace period.
    await _seeded_and_acknowledged_job(job_store, gateway_id="gw-1", ack_received_at=NOW - timedelta(seconds=10))
    await health_store.upsert(
        GatewayStatus(
            gateway_id="gw-1", tenant_id=None, last_heartbeat_at=NOW - timedelta(seconds=400),
            gateway_version="1.0", container_runtime_status="DOWN", last_successful_job_at=None, last_error=None,
        )
    )
    clock = FakeClock(NOW)

    reissued = await reissue_orphaned_jobs(
        job_store=job_store, health_store=health_store, clock=clock, sla_seconds=600.0,
        degraded_after_seconds=DEGRADED_AFTER, unreachable_after_seconds=UNREACHABLE_AFTER, failed_after_seconds=FAILED_AFTER,
    )

    assert reissued == 0
    assert (await job_store.list_all())[0].state == JobState.ACKNOWLEDGED


async def test_reissue_orphaned_jobs_leaves_a_job_from_a_healthy_gateway_alone() -> None:
    job_store = MemoryJobStore(clock=FakeClock(NOW))
    health_store = MemoryHealthStore()
    await _seeded_and_acknowledged_job(job_store, gateway_id="gw-1", ack_received_at=NOW - timedelta(seconds=700))
    await health_store.upsert(
        GatewayStatus(
            gateway_id="gw-1", tenant_id=None, last_heartbeat_at=NOW,  # fresh heartbeat -> HEALTHY
            gateway_version="1.0", container_runtime_status="UP", last_successful_job_at=None, last_error=None,
        )
    )
    clock = FakeClock(NOW)

    reissued = await reissue_orphaned_jobs(
        job_store=job_store, health_store=health_store, clock=clock, sla_seconds=600.0,
        degraded_after_seconds=DEGRADED_AFTER, unreachable_after_seconds=UNREACHABLE_AFTER, failed_after_seconds=FAILED_AFTER,
    )

    assert reissued == 0
    assert (await job_store.list_all())[0].state == JobState.ACKNOWLEDGED


async def test_reissue_orphaned_jobs_with_no_gateway_status_history_reissues_nothing() -> None:
    job_store = MemoryJobStore(clock=FakeClock(NOW))
    health_store = MemoryHealthStore()
    await _seeded_and_acknowledged_job(job_store, gateway_id="gw-1", ack_received_at=NOW - timedelta(seconds=700))
    clock = FakeClock(NOW)

    reissued = await reissue_orphaned_jobs(
        job_store=job_store, health_store=health_store, clock=clock, sla_seconds=600.0,
        degraded_after_seconds=DEGRADED_AFTER, unreachable_after_seconds=UNREACHABLE_AFTER, failed_after_seconds=FAILED_AFTER,
    )

    assert reissued == 0


async def test_reissued_job_becomes_claimable_by_a_different_gateway() -> None:
    """End-to-end proof of the "gateway is replaceable without losing
    functional state" claim: the original gateway is gone for good, but
    the job survives and a different gateway can pick it up."""
    job_store = MemoryJobStore(clock=FakeClock(NOW))
    health_store = MemoryHealthStore()
    await _seeded_and_acknowledged_job(job_store, gateway_id="gw-old", ack_received_at=NOW - timedelta(seconds=700))
    await health_store.upsert(
        GatewayStatus(
            gateway_id="gw-old", tenant_id=None, last_heartbeat_at=NOW - timedelta(seconds=3000),  # FAILED
            gateway_version="1.0", container_runtime_status="DOWN", last_successful_job_at=None, last_error=None,
        )
    )
    clock = FakeClock(NOW)

    reissued = await reissue_orphaned_jobs(
        job_store=job_store, health_store=health_store, clock=clock, sla_seconds=600.0,
        degraded_after_seconds=DEGRADED_AFTER, unreachable_after_seconds=UNREACHABLE_AFTER, failed_after_seconds=FAILED_AFTER,
    )
    assert reissued == 1

    claimed = await job_store.claim(gateway_id="gw-new", job_types=None, manifest_versions=None, max_jobs=1, dispatch_slots=None)
    assert len(claimed) == 1
    assert claimed[0].job_id == "job-1"
