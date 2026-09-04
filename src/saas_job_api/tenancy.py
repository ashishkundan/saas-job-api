"""Tenant / Target / Schedule domain types (Phase 2.5).

Schedule recurrence is a plain interval_seconds rather than a cron
expression - the plan only calls for "a periodic function turning due
schedules into JobRecords", and a cron parser would be a new third-party
dependency (or a hand-rolled evaluator) for expressiveness nothing here
actually needs yet. next_run_at is what scheduler_tick.py (2.5's second
half) actually queries against; interval_seconds is only used to compute
the next one after a schedule fires.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


def new_tenant_id() -> str:
    return f"tenant_{uuid.uuid4().hex[:12]}"


def new_target_id() -> str:
    return f"target_{uuid.uuid4().hex[:12]}"


def new_schedule_id() -> str:
    return f"sched_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Tenant:
    tenant_id: str
    name: str
    created_at: datetime
    is_active: bool = True


@dataclass(slots=True)
class Target:
    """credential_ref is a pointer only (Gateway VM's Credential Broker,
    Phase 1.3, resolves it to secret material) - never a secret itself, so
    it's safe to store and return here like any other field."""

    target_id: str
    tenant_id: str
    name: str
    host: str
    port: int
    plugin_ref: str
    plugin_version: str
    created_at: datetime
    credential_ref: str | None = None


@dataclass(slots=True)
class Schedule:
    schedule_id: str
    tenant_id: str
    target_id: str
    job_type: str
    manifest_version: str
    interval_seconds: int
    next_run_at: datetime
    created_at: datetime
    enabled: bool = True
    last_run_at: datetime | None = None
