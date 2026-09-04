"""Abstract base class for job store implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .domain import JobRecord
from .time_provider import Clock


class JobStoreBase(ABC):
    """Abstract interface for job storage (memory or database)."""

    @abstractmethod
    async def seed(self, record: JobRecord) -> JobRecord:
        """Store a job record. Raise ValueError if job_id already exists."""
        pass

    @abstractmethod
    async def reset(self) -> None:
        """Delete all jobs and clear pending faults (dev-only)."""
        pass

    @abstractmethod
    async def list_all(self) -> list[JobRecord]:
        """Return all job records in any state."""
        pass

    @abstractmethod
    async def set_fault(self, status_code: int, retry_after_seconds: float | None) -> None:
        """Inject a transient fault for the next poll (dev-only testing)."""
        pass

    @abstractmethod
    async def take_fault(self) -> tuple[int, float | None] | None:
        """Retrieve and clear the pending fault. Return (status_code, retry_after) or None."""
        pass

    @abstractmethod
    async def claim(
        self,
        *,
        gateway_id: str,
        job_types: list[str] | None,
        manifest_versions: list[str] | None,
        max_jobs: int,
        dispatch_slots: int | None,
    ) -> list[JobRecord]:
        """Claim up to max_jobs eligible jobs for a gateway. Atomically transitions AVAILABLE→RESERVED."""
        pass

    @abstractmethod
    async def acknowledge(
        self,
        *,
        job_id: str,
        gateway_id: str,
        receipt_token: str,
        received_at: datetime,
        payload_hash: str | None,
        local_record_version: int | None,
    ) -> JobRecord:
        """Acknowledge job receipt. Transitions RESERVED→ACKNOWLEDGED. Raise ConflictError on mismatch."""
        pass

    @abstractmethod
    async def reissue_orphaned(
        self, *, now: datetime, unreachable_gateway_ids: set[str], sla_seconds: float
    ) -> list[JobRecord]:
        """Reset any ACKNOWLEDGED job whose ack_gateway_id is in
        unreachable_gateway_ids and whose ack_received_at is at least
        sla_seconds in the past, back to AVAILABLE - clearing every
        reservation/ack field so it's indistinguishable from a fresh job
        (Phase 2.5's orphaned-job reissue rule). The gateway that
        acknowledged it may have been permanently replaced under a
        brand-new gateway_id (registration, 1.1b), so nothing else would
        ever un-stick it. Note: a RESERVED (not yet acknowledged) job
        already self-heals via the existing reservation_until TTL in
        claim()'s eligibility check - this method only needs to cover the
        ACKNOWLEDGED case, which had no timeout at all before this.
        Returns the now-reset records."""
        pass
