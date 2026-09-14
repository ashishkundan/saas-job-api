"""Scheduled purge of audit_events past their mandatory retention floor
(Phase 2.7).

audit_events is append-only for its entire retention period - nothing in
this module (or AuditLogStoreBase.purge_expired()) can delete a row that
hasn't already outlived Settings.audit_retention_days (default 7 years).
Mirrors certificate-discovery-engine's gateway_vm/retention.py
(RetentionSweeper) shape: a pure sweep_once() plus a looping run(), so
the sweep is directly unit-testable without waiting on a real clock.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from .audit_store_base import AuditLogStoreBase
from .time_provider import Clock

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuditRetentionSweeper:
    """Purges audit_events rows older than retention_days, one bounded batch at a time."""

    store: AuditLogStoreBase
    clock: Clock
    retention_days: int
    batch_size: int
    interval_seconds: float = 3_600.0

    async def sweep_once(self) -> int:
        """Purge one bounded batch of audit events past the retention floor."""

        before = self.clock.now() - timedelta(days=self.retention_days)
        return await self.store.purge_expired(before=before, limit=self.batch_size)

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Run the retention sweep until shutdown, logging (not raising) any failure."""

        while not shutdown_event.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("audit_retention: sweep failed")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue
