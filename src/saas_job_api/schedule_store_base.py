"""Abstract base class for Schedule storage (Phase 2.5).

CRUD only here - claim_due() (the SELECT ... FOR UPDATE SKIP LOCKED
operation scheduler_tick.py needs to avoid double-firing across the 2
render.yaml web instances) is added to these same classes alongside
scheduler_tick.py itself, since it's scheduling-engine plumbing rather
than plain resource management.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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
