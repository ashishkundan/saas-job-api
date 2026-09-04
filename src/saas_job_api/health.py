"""GatewayStatus domain type and its timing-based derivation rule (Phase 1.4).

current_status is derived, not just stored - it must reflect elapsed time
since the last heartbeat even without a new heartbeat arriving (a Gateway
that goes silent must eventually show as UNREACHABLE/FAILED on its own,
not stay HEALTHY forever just because nothing re-computed it). Thresholds
are settings, not hard-coded, per the doc's explicit guidance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class HealthState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNREACHABLE = "UNREACHABLE"
    FAILED = "FAILED"


@dataclass(slots=True)
class GatewayStatus:
    gateway_id: str
    tenant_id: str | None
    last_heartbeat_at: datetime
    gateway_version: str | None
    container_runtime_status: str | None
    last_successful_job_at: datetime | None
    last_error: str | None
    # The Gateway's own self-reported overall status from its most recent
    # heartbeat (Heartbeat.status on the Gateway VM side) - an explicit
    # FAILED report overrides the timing-derived state immediately, per
    # the doc's "explicit crash report" rule.
    last_reported_status: HealthState | None = None


def derive_current_status(
    status: GatewayStatus,
    *,
    now: datetime,
    degraded_after_seconds: float,
    unreachable_after_seconds: float,
    failed_after_seconds: float,
) -> HealthState:
    if status.last_reported_status == HealthState.FAILED:
        return HealthState.FAILED

    elapsed = (now - status.last_heartbeat_at).total_seconds()
    if elapsed < degraded_after_seconds:
        return HealthState.HEALTHY
    if elapsed < unreachable_after_seconds:
        return HealthState.DEGRADED
    if elapsed < failed_after_seconds:
        return HealthState.UNREACHABLE
    return HealthState.FAILED
