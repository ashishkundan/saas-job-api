"""In-memory certificate inventory store for development and testing."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .inventory import CertificateRecord, SubmitResultOutcome
from .inventory_store_base import InventoryStoreBase


@dataclass
class MemoryInventoryStore(InventoryStoreBase):
    # (job_id, attempt_token) -> record_count - the idempotency marker,
    # mirroring the job_results table's unique constraint on Postgres.
    _markers: dict[tuple[str, str], int] = field(default_factory=dict)
    _records: dict[str, CertificateRecord] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def submit_result(
        self,
        *,
        job_id: str,
        attempt_token: str,
        tenant_id: str | None,
        target_id: str | None,
        plugin_id: str,
        plugin_version: str,
        certificates: list[dict[str, Any]],
        received_at: datetime,
    ) -> SubmitResultOutcome:
        async with self._lock:
            key = (job_id, attempt_token)
            existing_count = self._markers.get(key)
            if existing_count is not None:
                return SubmitResultOutcome(accepted=True, dedupe=True, record_count=existing_count)

            records = []
            for raw in certificates:
                record = CertificateRecord(
                    record_id=str(uuid.uuid4()),
                    job_id=job_id,
                    attempt_token=attempt_token,
                    tenant_id=tenant_id,
                    target_id=target_id,
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    subject=raw["subject"],
                    issuer=raw["issuer"],
                    serial_number=raw["serialNumber"],
                    valid_from=raw["validFrom"],
                    valid_to=raw["validTo"],
                    fingerprint=raw["fingerprint"],
                    received_at=received_at,
                )
                self._records[record.record_id] = record
                records.append(record)

            self._markers[key] = len(records)
            return SubmitResultOutcome(accepted=True, dedupe=False, record_count=len(records), records=tuple(records))

    async def list_by_tenant(self, tenant_id: str, *, limit: int) -> list[CertificateRecord]:
        async with self._lock:
            matches = [r for r in self._records.values() if r.tenant_id == tenant_id]
            matches.sort(key=lambda r: r.received_at, reverse=True)
            return matches[: max(limit, 0)]
