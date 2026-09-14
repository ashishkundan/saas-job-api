"""PostgreSQL-backed audit log store."""

from __future__ import annotations

import json
from datetime import datetime

from asyncpg import Pool

from .audit import AuditEvent
from .audit_store_base import AuditLogStoreBase


class PostgresAuditLogStore(AuditLogStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def append(self, event: AuditEvent) -> AuditEvent:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_events "
                "(event_id, event_type, actor, tenant_id, resource_type, resource_id, detail, occurred_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                event.event_id,
                event.event_type,
                event.actor,
                event.tenant_id,
                event.resource_type,
                event.resource_id,
                json.dumps(event.detail),
                event.occurred_at,
            )
        return event

    async def list_recent(self, *, tenant_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        async with self.pool.acquire() as conn:
            if tenant_id is None:
                rows = await conn.fetch("SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT $1", limit)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM audit_events WHERE tenant_id = $1 ORDER BY occurred_at DESC LIMIT $2",
                    tenant_id,
                    limit,
                )
        return [self._row_to_event(row) for row in rows]

    async def purge_expired(self, *, before: datetime, limit: int) -> int:
        async with self.pool.acquire() as conn:
            # DELETE has no LIMIT in Postgres - the oldest-`limit` rows
            # past the cutoff are selected first, then deleted by id.
            result = await conn.execute(
                "DELETE FROM audit_events WHERE event_id IN ("
                "SELECT event_id FROM audit_events WHERE occurred_at < $1 ORDER BY occurred_at LIMIT $2"
                ")",
                before,
                limit,
            )
        # asyncpg execute() returns a string like "DELETE 42".
        return int(result.split()[-1])

    @staticmethod
    def _row_to_event(row) -> AuditEvent:
        return AuditEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            actor=row["actor"],
            tenant_id=row["tenant_id"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            detail=json.loads(row["detail"]),
            occurred_at=row["occurred_at"],
        )
