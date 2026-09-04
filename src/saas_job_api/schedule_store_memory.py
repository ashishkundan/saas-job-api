"""In-memory Schedule store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .errors import NotFoundError
from .tenancy import Schedule
from .schedule_store_base import ScheduleStoreBase


@dataclass
class MemoryScheduleStore(ScheduleStoreBase):
    _schedules: dict[str, Schedule] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def create(self, schedule: Schedule) -> Schedule:
        async with self._lock:
            if schedule.schedule_id in self._schedules:
                raise ValueError(f"schedule_id already exists: {schedule.schedule_id}")
            self._schedules[schedule.schedule_id] = schedule
            return schedule

    async def get(self, tenant_id: str, schedule_id: str) -> Schedule | None:
        async with self._lock:
            schedule = self._schedules.get(schedule_id)
            return schedule if schedule is not None and schedule.tenant_id == tenant_id else None

    async def list_by_tenant(self, tenant_id: str) -> list[Schedule]:
        async with self._lock:
            return [s for s in self._schedules.values() if s.tenant_id == tenant_id]

    async def delete(self, tenant_id: str, schedule_id: str) -> None:
        async with self._lock:
            schedule = self._schedules.get(schedule_id)
            if schedule is None or schedule.tenant_id != tenant_id:
                raise NotFoundError(f"schedule not found: {schedule_id}")
            del self._schedules[schedule_id]

    async def claim_due(self, *, now: datetime, limit: int) -> list[Schedule]:
        async with self._lock:
            due = [s for s in self._schedules.values() if s.enabled and s.next_run_at <= now]
            due.sort(key=lambda s: s.next_run_at)
            claimed = due[: max(limit, 0)]
            for schedule in claimed:
                schedule.last_run_at = now
                schedule.next_run_at = now + timedelta(seconds=schedule.interval_seconds)
            return list(claimed)
