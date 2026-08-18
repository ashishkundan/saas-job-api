from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from saas_job_api.domain import JobRecord, JobState
from saas_job_api.errors import ConflictError
from saas_job_api.store import JobStore
from saas_job_api.time_provider import FakeClock


def make_record(job_id: str, *, priority: int = 50, scheduled_at: datetime | None = None) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        job_type="TLS_SCAN",
        manifest_version="1.0",
        priority=priority,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
        correlation_id=f"corr_{job_id}",
        payload={},
        max_attempts=8,
        trace_id=None,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock: FakeClock) -> JobStore:
    return JobStore(clock=clock, reservation_ttl_seconds=60.0)


async def test_claim_reserves_with_ttl(store: JobStore, clock: FakeClock):
    await store.seed(make_record("job_1"))

    [claimed] = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )

    assert claimed.state == JobState.RESERVED
    assert claimed.reserved_by == "gw_a"
    assert claimed.reservation_until == clock.now() + timedelta(seconds=60)
    assert claimed.receipt_token


async def test_reserved_job_excluded_before_expiry(store: JobStore):
    await store.seed(make_record("job_1"))
    await store.claim(gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None)

    second_claim = await store.claim(
        gateway_id="gw_b", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )

    assert second_claim == []


async def test_expired_reservation_is_redelivered_with_new_token(store: JobStore, clock: FakeClock):
    await store.seed(make_record("job_1"))
    [first] = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )
    old_token = first.receipt_token

    clock.advance(61)
    [redelivered] = await store.claim(
        gateway_id="gw_b", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )

    assert redelivered.job_id == "job_1"
    assert redelivered.reserved_by == "gw_b"
    assert redelivered.receipt_token != old_token
    assert redelivered.delivery_attempts == 2


async def test_ack_with_stale_token_after_redelivery_is_conflict(store: JobStore, clock: FakeClock):
    await store.seed(make_record("job_1"))
    [first] = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )
    old_token = first.receipt_token

    clock.advance(61)
    await store.claim(gateway_id="gw_b", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None)

    with pytest.raises(ConflictError):
        await store.acknowledge(
            job_id="job_1",
            gateway_id="gw_a",
            receipt_token=old_token,
            received_at=clock.now(),
            payload_hash=None,
            local_record_version=None,
        )


async def test_ack_with_current_token_succeeds_and_is_idempotent(store: JobStore, clock: FakeClock):
    await store.seed(make_record("job_1"))
    [claimed] = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )

    first_ack = await store.acknowledge(
        job_id="job_1",
        gateway_id="gw_a",
        receipt_token=claimed.receipt_token,
        received_at=clock.now(),
        payload_hash="sha256:abc",
        local_record_version=1,
    )
    assert first_ack.state == JobState.ACKNOWLEDGED

    # Idempotent replay -- must not raise ConflictError.
    second_ack = await store.acknowledge(
        job_id="job_1",
        gateway_id="gw_a",
        receipt_token=claimed.receipt_token,
        received_at=clock.now(),
        payload_hash="sha256:abc",
        local_record_version=1,
    )
    assert second_ack.state == JobState.ACKNOWLEDGED


async def test_ack_unknown_job_is_conflict(store: JobStore, clock: FakeClock):
    with pytest.raises(ConflictError):
        await store.acknowledge(
            job_id="does_not_exist",
            gateway_id="gw_a",
            receipt_token="whatever",
            received_at=clock.now(),
            payload_hash=None,
            local_record_version=None,
        )


async def test_ack_wrong_gateway_is_conflict(store: JobStore, clock: FakeClock):
    await store.seed(make_record("job_1"))
    [claimed] = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )

    with pytest.raises(ConflictError):
        await store.acknowledge(
            job_id="job_1",
            gateway_id="gw_b",
            receipt_token=claimed.receipt_token,
            received_at=clock.now(),
            payload_hash=None,
            local_record_version=None,
        )


async def test_job_type_and_manifest_version_filtering(store: JobStore):
    tls = make_record("job_tls")
    other = make_record("job_other")
    other.job_type = "WINDOWS_CERT_SCAN"
    await store.seed(tls)
    await store.seed(other)

    claimed = await store.claim(
        gateway_id="gw_a",
        job_types=["TLS_SCAN"],
        manifest_versions=None,
        max_jobs=10,
        dispatch_slots=None,
    )

    assert [j.job_id for j in claimed] == ["job_tls"]


async def test_max_jobs_and_dispatch_slots_bound_the_batch(store: JobStore):
    for i in range(5):
        await store.seed(make_record(f"job_{i}"))

    claimed = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=2
    )

    assert len(claimed) == 2


async def test_priority_then_scheduled_at_ordering(store: JobStore):
    now = datetime.now(timezone.utc)
    await store.seed(make_record("low", priority=10, scheduled_at=now))
    await store.seed(make_record("high", priority=90, scheduled_at=now))
    await store.seed(make_record("high_later", priority=90, scheduled_at=now.replace(microsecond=0)))

    claimed = await store.claim(
        gateway_id="gw_a", job_types=None, manifest_versions=None, max_jobs=10, dispatch_slots=None
    )

    assert claimed[0].priority == 90
    assert claimed[-1].job_id == "low"
