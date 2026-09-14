"""In-memory audit log store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from .audit import AuditEvent
from .audit_store_base import AuditLogStoreBase


@dataclass
class MemoryAuditLogStore(AuditLogStoreBase):
    _events: list[AuditEvent] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def append(self, event: AuditEvent) -> AuditEvent:
        async with self._lock:
            self._events.append(event)
            return event

    async def list_recent(self, *, tenant_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        async with self._lock:
            matches = [e for e in self._events if tenant_id is None or e.tenant_id == tenant_id]
            matches.sort(key=lambda e: e.occurred_at, reverse=True)
            return matches[: max(limit, 0)]

    async def purge_expired(self, *, before: datetime, limit: int) -> int:
        async with self._lock:
            expired_ids = {e.event_id for e in self._events if e.occurred_at < before}
            if len(expired_ids) > limit:
                oldest_first = sorted((e for e in self._events if e.event_id in expired_ids), key=lambda e: e.occurred_at)
                expired_ids = {e.event_id for e in oldest_first[:limit]}
            if not expired_ids:
                return 0
            self._events = [e for e in self._events if e.event_id not in expired_ids]
            return len(expired_ids)
