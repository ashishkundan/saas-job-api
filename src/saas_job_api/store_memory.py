"""In-memory job store: reservation/redelivery/idempotency logic."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .domain import JobRecord, JobState
from .errors import ConflictError
from .store_base import JobStoreBase
from .time_provider import Clock, RealClock


@dataclass
class PendingFault:
    status_code: int
    retry_after_seconds: float | None = None


@dataclass
class MemoryJobStore(JobStoreBase):
    """In-memory job store for development and testing."""

    clock: Clock = field(default_factory=RealClock)
    reservation_ttl_seconds: float = 60.0
    _jobs: dict[str, JobRecord] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _pending_fault: PendingFault | None = None

    async def seed(self, record: JobRecord) -> JobRecord:
        async with self._lock:
            if record.job_id in self._jobs:
                raise ValueError(f"job_id already exists: {record.job_id}")
            self._jobs[record.job_id] = record
            return record

    async def reset(self) -> None:
        async with self._lock:
            self._jobs.clear()
            self._pending_fault = None

    async def list_all(self) -> list[JobRecord]:
        async with self._lock:
            return list(self._jobs.values())

    async def set_fault(self, status_code: int, retry_after_seconds: float | None) -> None:
        async with self._lock:
            self._pending_fault = PendingFault(status_code, retry_after_seconds)

    async def take_fault(self) -> tuple[int, float | None] | None:
        async with self._lock:
            if self._pending_fault is None:
                return None
            fault, self._pending_fault = self._pending_fault, None
            return (fault.status_code, fault.retry_after_seconds)

    async def claim(
        self,
        *,
        gateway_id: str,
        job_types: list[str] | None,
        manifest_versions: list[str] | None,
        max_jobs: int,
        dispatch_slots: int | None,
    ) -> list[JobRecord]:
        async with self._lock:
            now = self.clock.now()
            eligible = [
                job
                for job in self._jobs.values()
                if job.is_eligible(now)
                and (job_types is None or job.job_type in job_types)
                and (manifest_versions is None or job.manifest_version in manifest_versions)
            ]
            eligible.sort(key=lambda job: (-job.priority, job.scheduled_at, job.job_id))

            limit = max_jobs if dispatch_slots is None else min(max_jobs, dispatch_slots)
            chosen = eligible[: max(limit, 0)]

            reservation_until = now + timedelta(seconds=self.reservation_ttl_seconds)
            for job in chosen:
                job.state = JobState.RESERVED
                job.reserved_by = gateway_id
                job.reservation_until = reservation_until
                job.receipt_token = secrets.token_urlsafe(24)
                job.delivery_attempts += 1
            return list(chosen)

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
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ConflictError("unknown job")
            if (job_id, receipt_token) in job.acknowledged_receipts:
                return job  # idempotent replay
            if job.receipt_token != receipt_token:
                raise ConflictError("stale or invalid receipt token")
            if job.reserved_by != gateway_id:
                raise ConflictError("gateway/job binding mismatch")

            job.state = JobState.ACKNOWLEDGED
            job.acknowledged_receipts.add((job_id, receipt_token))
            job.ack_gateway_id = gateway_id
            job.ack_received_at = received_at
            job.ack_payload_hash = payload_hash
            job.ack_local_record_version = local_record_version
            return job
