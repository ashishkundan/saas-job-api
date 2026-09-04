"""PostgreSQL-backed Schedule store."""

from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg
from asyncpg import Pool

from .errors import NotFoundError
from .tenancy import Schedule
from .schedule_store_base import ScheduleStoreBase


class PostgresScheduleStore(ScheduleStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def create(self, schedule: Schedule) -> Schedule:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO schedules "
                    "(schedule_id, tenant_id, target_id, job_type, manifest_version, interval_seconds, "
                    "next_run_at, created_at, enabled, last_run_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                    schedule.schedule_id,
                    schedule.tenant_id,
                    schedule.target_id,
                    schedule.job_type,
                    schedule.manifest_version,
                    schedule.interval_seconds,
                    schedule.next_run_at,
                    schedule.created_at,
                    schedule.enabled,
                    schedule.last_run_at,
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"schedule_id already exists: {schedule.schedule_id}")
        return schedule

    async def get(self, tenant_id: str, schedule_id: str) -> Schedule | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM schedules WHERE schedule_id = $1 AND tenant_id = $2", schedule_id, tenant_id
            )
        return self._row_to_schedule(row) if row is not None else None

    async def list_by_tenant(self, tenant_id: str) -> list[Schedule]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM schedules WHERE tenant_id = $1 ORDER BY created_at", tenant_id)
        return [self._row_to_schedule(row) for row in rows]

    async def delete(self, tenant_id: str, schedule_id: str) -> None:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM schedules WHERE schedule_id = $1 AND tenant_id = $2", schedule_id, tenant_id
            )
        if result == "DELETE 0":
            raise NotFoundError(f"schedule not found: {schedule_id}")

    async def claim_due(self, *, now: datetime, limit: int) -> list[Schedule]:
        # FOR UPDATE SKIP LOCKED only holds row locks for the duration of a
        # transaction - it must be an explicit conn.transaction(), not the
        # implicit per-statement autocommit asyncpg otherwise uses, or the
        # lock (and the point of SKIP LOCKED) would be gone before the
        # UPDATE below could rely on it.
        claimed: list[Schedule] = []
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT * FROM schedules WHERE enabled = true AND next_run_at <= $1 "
                    "ORDER BY next_run_at LIMIT $2 FOR UPDATE SKIP LOCKED",
                    now,
                    limit,
                )
                for row in rows:
                    next_run_at = now + timedelta(seconds=row["interval_seconds"])
                    await conn.execute(
                        "UPDATE schedules SET next_run_at = $1, last_run_at = $2 WHERE schedule_id = $3",
                        next_run_at,
                        now,
                        row["schedule_id"],
                    )
                    claimed.append(
                        Schedule(
                            schedule_id=row["schedule_id"],
                            tenant_id=row["tenant_id"],
                            target_id=row["target_id"],
                            job_type=row["job_type"],
                            manifest_version=row["manifest_version"],
                            interval_seconds=row["interval_seconds"],
                            next_run_at=next_run_at,
                            created_at=row["created_at"],
                            enabled=row["enabled"],
                            last_run_at=now,
                        )
                    )
        return claimed

    @staticmethod
    def _row_to_schedule(row) -> Schedule:
        return Schedule(
            schedule_id=row["schedule_id"],
            tenant_id=row["tenant_id"],
            target_id=row["target_id"],
            job_type=row["job_type"],
            manifest_version=row["manifest_version"],
            interval_seconds=row["interval_seconds"],
            next_run_at=row["next_run_at"],
            created_at=row["created_at"],
            enabled=row["enabled"],
            last_run_at=row["last_run_at"],
        )
