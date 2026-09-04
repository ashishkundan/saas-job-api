"""PostgreSQL-backed job store with ACID transactions."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any

import asyncpg
from asyncpg import Pool

from .domain import JobRecord, JobState
from .errors import ConflictError
from .store_base import JobStoreBase
from .time_provider import Clock, RealClock


class PostgresJobStore(JobStoreBase):
    """PostgreSQL-backed job store for production deployments."""

    def __init__(self, pool: Pool, clock: Clock | None = None, reservation_ttl_seconds: float = 60.0):
        self.pool = pool
        self.clock = clock or RealClock()
        self.reservation_ttl_seconds = reservation_ttl_seconds
        self._pending_fault: tuple[int, float | None] | None = None

    async def seed(self, record: JobRecord) -> JobRecord:
        """Insert a job record. Raise ValueError if job_id already exists."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO jobs (job_id, job_type, manifest_version, priority, payload, "
                    "max_attempts, state, correlation_id, trace_id, scheduled_at, "
                    "acknowledged_receipts, created_at, updated_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $12)",
                    record.job_id,
                    record.job_type,
                    record.manifest_version,
                    record.priority,
                    json.dumps(record.payload),
                    record.max_attempts,
                    record.state.value,
                    record.correlation_id,
                    record.trace_id,
                    record.scheduled_at,
                    json.dumps([]),
                    datetime.now(tz=None),
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"job_id already exists: {record.job_id}")
        return record

    async def reset(self) -> None:
        """Delete all jobs (dev-only)."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM jobs")

    async def list_all(self) -> list[JobRecord]:
        """Fetch all jobs from database."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM jobs ORDER BY created_at DESC")
        return [self._row_to_record(row) for row in rows]

    async def set_fault(self, status_code: int, retry_after_seconds: float | None) -> None:
        """Store a transient fault (in-memory, for testing)."""
        self._pending_fault = (status_code, retry_after_seconds)

    async def take_fault(self) -> tuple[int, float | None] | None:
        """Retrieve and clear the pending fault."""
        fault, self._pending_fault = self._pending_fault, None
        return fault

    async def claim(
        self,
        *,
        gateway_id: str,
        job_types: list[str] | None,
        manifest_versions: list[str] | None,
        max_jobs: int,
        dispatch_slots: int | None,
    ) -> list[JobRecord]:
        """Claim eligible jobs via database transaction."""
        now = self.clock.now()
        reservation_until = now + timedelta(seconds=self.reservation_ttl_seconds)
        limit = max_jobs if dispatch_slots is None else min(max_jobs, dispatch_slots)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT * FROM jobs WHERE (state = 'AVAILABLE' OR "
                    "(state = 'RESERVED' AND reservation_until <= $2)) "
                    "ORDER BY priority DESC, scheduled_at ASC, job_id ASC LIMIT $1 FOR UPDATE",
                    limit, now
                )

                chosen_ids = [row["job_id"] for row in rows]
                if chosen_ids:
                    for job_id in chosen_ids:
                        receipt_token = secrets.token_urlsafe(24)
                        await conn.execute(
                            "UPDATE jobs SET state = 'RESERVED', reserved_by = $1, "
                            "reservation_until = $2, receipt_token = $3, "
                            "delivery_attempts = delivery_attempts + 1, updated_at = $4 "
                            "WHERE job_id = $5",
                            gateway_id, reservation_until, receipt_token, 
                            datetime.now(tz=None), job_id
                        )

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM jobs WHERE job_id = ANY($1)", chosen_ids)
        return [self._row_to_record(row) for row in rows]

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
        """Acknowledge job receipt via database transaction."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
                if row is None:
                    raise ConflictError("unknown job")

                acknowledged_receipts = json.loads(row["acknowledged_receipts"])
                if [job_id, receipt_token] in acknowledged_receipts:
                    return self._row_to_record(row)

                if row["receipt_token"] != receipt_token:
                    raise ConflictError("stale or invalid receipt token")
                if row["reserved_by"] != gateway_id:
                    raise ConflictError("gateway/job binding mismatch")

                acknowledged_receipts.append([job_id, receipt_token])
                await conn.execute(
                    "UPDATE jobs SET state = 'ACKNOWLEDGED', ack_gateway_id = $1, "
                    "ack_received_at = $2, ack_payload_hash = $3, ack_local_record_version = $4, "
                    "acknowledged_receipts = $5, updated_at = $6 WHERE job_id = $7",
                    gateway_id, received_at, payload_hash, local_record_version,
                    json.dumps(acknowledged_receipts), datetime.now(tz=None), job_id
                )

                updated_row = await conn.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
        return self._row_to_record(updated_row)

    async def reissue_orphaned(
        self, *, now: datetime, unreachable_gateway_ids: set[str], sla_seconds: float
    ) -> list[JobRecord]:
        if not unreachable_gateway_ids:
            return []
        threshold = now - timedelta(seconds=sla_seconds)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT job_id FROM jobs WHERE state = 'ACKNOWLEDGED' AND ack_gateway_id = ANY($1) "
                    "AND ack_received_at <= $2 FOR UPDATE",
                    list(unreachable_gateway_ids),
                    threshold,
                )
                job_ids = [row["job_id"] for row in rows]
                if job_ids:
                    await conn.execute(
                        "UPDATE jobs SET state = 'AVAILABLE', reserved_by = NULL, reservation_until = NULL, "
                        "receipt_token = NULL, ack_gateway_id = NULL, ack_received_at = NULL, "
                        "ack_payload_hash = NULL, ack_local_record_version = NULL, updated_at = $2 "
                        "WHERE job_id = ANY($1)",
                        job_ids,
                        datetime.now(tz=None),
                    )

        if not job_ids:
            return []
        async with self.pool.acquire() as conn:
            updated_rows = await conn.fetch("SELECT * FROM jobs WHERE job_id = ANY($1)", job_ids)
        return [self._row_to_record(row) for row in updated_rows]

    def _row_to_record(self, row: asyncpg.Record) -> JobRecord:
        """Convert database row to JobRecord."""
        return JobRecord(
            job_id=row["job_id"],
            job_type=row["job_type"],
            manifest_version=row["manifest_version"],
            priority=row["priority"],
            scheduled_at=row["scheduled_at"],
            correlation_id=row["correlation_id"],
            payload=json.loads(row["payload"]),
            max_attempts=row["max_attempts"],
            trace_id=row["trace_id"],
            state=JobState(row["state"]),
            receipt_token=row["receipt_token"],
            reserved_by=row["reserved_by"],
            reservation_until=row["reservation_until"],
            delivery_attempts=row["delivery_attempts"],
            ack_gateway_id=row["ack_gateway_id"],
            ack_received_at=row["ack_received_at"],
            ack_payload_hash=row["ack_payload_hash"],
            ack_local_record_version=row["ack_local_record_version"],
            acknowledged_receipts=set(
                tuple(pair) for pair in json.loads(row["acknowledged_receipts"])
            ),
        )
