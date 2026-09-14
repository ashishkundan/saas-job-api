"""Abstract base class for audit log storage (Phase 2.7).

No *update* method exists here, and deliberately so - an append-only
log's tamper-resistance starts with there being no method on this
interface that could ever mutate a past event. purge_expired() is the
one exception to "no delete": it is floor-anchored (only rows already
past the mandatory retention period, e.g. 7 years, are eligible) rather
than targeted at a specific event, so it cannot be used to selectively
remove a recent/inconvenient record - only bulk-expire what compliance
no longer requires the store to retain at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .audit import AuditEvent


class AuditLogStoreBase(ABC):
    @abstractmethod
    async def append(self, event: AuditEvent) -> AuditEvent:
        """Persist one audit event."""

    @abstractmethod
    async def list_recent(self, *, tenant_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        """Most-recent-first audit events, optionally scoped to one tenant."""

    @abstractmethod
    async def purge_expired(self, *, before: datetime, limit: int) -> int:
        """Delete one bounded batch of events with occurred_at < before.

        Returns the number of rows deleted. Callers must only ever pass a
        `before` that already satisfies the retention floor (see
        Settings.audit_retention_days) - this method itself does not
        enforce that floor, the caller (AuditRetentionSweeper) does.
        """
