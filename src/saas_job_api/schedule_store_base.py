"""Abstract base class for Schedule storage (Phase 2.5)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .tenancy import Schedule


class ScheduleStoreBase(ABC):
    @abstractmethod
    async def create(self, schedule: Schedule) -> Schedule:
        """Persist a new schedule. Raise ValueError if schedule_id already exists."""

    @abstractmethod
    async def get(self, tenant_id: str, schedule_id: str) -> Schedule | None:
        """Look up one schedule, scoped to tenant_id."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: str) -> list[Schedule]:
        """Return every schedule belonging to one tenant."""

    @abstractmethod
    async def delete(self, tenant_id: str, schedule_id: str) -> None:
        """Remove one schedule. Raise NotFoundError if it doesn't exist for that tenant."""

    @abstractmethod
    async def claim_due(self, *, now: datetime, limit: int) -> list[Schedule]:
        """Atomically claim up to `limit` enabled schedules with
        next_run_at <= now, advancing each claimed schedule's next_run_at
        to now + interval_seconds and last_run_at to now as part of the
        same atomic operation - not a separate step. That's what actually
        prevents scheduler_tick.py from double-firing across the 2
        render.yaml web instances (confirmed 2026-09-04: SELECT ... FOR
        UPDATE SKIP LOCKED for the Postgres adapter): a schedule claimed by
        one caller is no longer due by the time any concurrent caller's
        claim could see it, rather than relying on a separate "claimed" flag
        that could itself race. Returns the schedules as claimed, with
        next_run_at/last_run_at already reflecting the advance."""
