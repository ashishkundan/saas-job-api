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
    async def get(self, job_id: str) -> JobRecord | None:
        """Look up one job by id, or None if it doesn't exist (Phase 2.6 -
        the results/interrupted routers need a job's payload, for its
        tenant_id/target_id, before recording anything against it)."""
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

    @abstractmethod
    async def reissue_one(self, *, job_id: str, gateway_id: str, now: datetime) -> JobRecord | None:
        """Immediately reset one ACKNOWLEDGED job back to AVAILABLE, without
        waiting for reissue_orphaned()'s SLA timer - used when the Gateway
        itself reports (POST /gateway/v1/jobs/{jobId}/interrupted, 2.6)
        that this specific job was RUNNING when its process restarted and
        its outcome is unknown, a stronger positive signal than mere
        gateway unreachability. A no-op (returns None) if the job doesn't
        exist, isn't ACKNOWLEDGED, or wasn't acknowledged by this
        gateway_id - this is a best-effort notification, not a strict
        contract the Gateway must get exactly right."""
        pass

    @abstractmethod
    async def mark_completed(self, *, job_id: str, gateway_id: str, now: datetime) -> JobRecord:
        """Transition an ACKNOWLEDGED job to COMPLETED once its result has
        been durably recorded (Phase 2.6). Idempotent: calling this again
        for an already-COMPLETED job is a no-op, matching the results
        endpoint's own dedupe semantics - a retried submission must be
        able to call this again safely. Raises ConflictError if gateway_id
        doesn't match the job's ack_gateway_id (mirrors acknowledge()'s
        own binding check), or NotFoundError for an unknown job_id."""
        pass
