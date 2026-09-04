"""Pure unit tests for derive_current_status - the state-transition matrix
the Phase 1.4 exit criteria calls for: on-time/delayed/missed sequences."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from saas_job_api.health import GatewayStatus, HealthState, derive_current_status

BASE_TIME = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
THRESHOLDS = dict(degraded_after_seconds=90.0, unreachable_after_seconds=300.0, failed_after_seconds=1_800.0)


def _status(**overrides) -> GatewayStatus:
    defaults = dict(
        gateway_id="gw-1",
        tenant_id=None,
        last_heartbeat_at=BASE_TIME,
        gateway_version="1.0",
        container_runtime_status="UP",
        last_successful_job_at=None,
        last_error=None,
        last_reported_status=None,
    )
    defaults.update(overrides)
    return GatewayStatus(**defaults)


def test_recent_heartbeat_is_healthy() -> None:
    status = _status()

    result = derive_current_status(status, now=BASE_TIME + timedelta(seconds=10), **THRESHOLDS)

    assert result == HealthState.HEALTHY


def test_one_missed_heartbeat_is_degraded() -> None:
    status = _status()

    result = derive_current_status(status, now=BASE_TIME + timedelta(seconds=100), **THRESHOLDS)

    assert result == HealthState.DEGRADED


def test_several_missed_heartbeats_is_unreachable() -> None:
    status = _status()

    result = derive_current_status(status, now=BASE_TIME + timedelta(seconds=305), **THRESHOLDS)

    assert result == HealthState.UNREACHABLE


def test_sustained_silence_past_failed_threshold_is_failed() -> None:
    status = _status()

    result = derive_current_status(status, now=BASE_TIME + timedelta(seconds=1_801), **THRESHOLDS)

    assert result == HealthState.FAILED


def test_exact_boundary_at_degraded_threshold_is_degraded_not_healthy() -> None:
    status = _status()

    result = derive_current_status(status, now=BASE_TIME + timedelta(seconds=90), **THRESHOLDS)

    assert result == HealthState.DEGRADED


def test_explicit_failed_report_overrides_a_recent_heartbeat() -> None:
    """The doc's 'explicit crash report' rule: a self-reported FAILED status
    is immediate, regardless of how recently the heartbeat itself arrived."""
    status = _status(last_reported_status=HealthState.FAILED)

    result = derive_current_status(status, now=BASE_TIME + timedelta(seconds=5), **THRESHOLDS)

    assert result == HealthState.FAILED


def test_a_recovered_gateway_returns_to_healthy_on_its_next_on_time_heartbeat() -> None:
    """Proves this is genuinely re-derived from the *latest* heartbeat, not
    a one-way ratchet - a gateway that was UNREACHABLE and then sends a
    fresh heartbeat is HEALTHY again."""
    stale = _status(last_heartbeat_at=BASE_TIME)
    assert derive_current_status(stale, now=BASE_TIME + timedelta(seconds=305), **THRESHOLDS) == HealthState.UNREACHABLE

    recovered = _status(last_heartbeat_at=BASE_TIME + timedelta(seconds=305))
    result = derive_current_status(recovered, now=BASE_TIME + timedelta(seconds=310), **THRESHOLDS)

    assert result == HealthState.HEALTHY
