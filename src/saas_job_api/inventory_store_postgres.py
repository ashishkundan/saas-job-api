"""PostgreSQL-backed certificate inventory store.

submit_result() relies on the job_results table's UNIQUE (job_id,
attempt_token) constraint (migration 005) as the actual idempotency
guarantee - the in-process check-then-insert here is an optimization to
avoid a wasted round-trip on the common "not a duplicate" path, not the
thing that makes concurrent duplicate submissions safe. The constraint is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import asyncpg
from asyncpg import Pool

from .inventory import CertificateRecord, SubmitResultOutcome
from .inventory_store_base import InventoryStoreBase


class PostgresInventoryStore(InventoryStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

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
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    "SELECT record_count FROM job_results WHERE job_id = $1 AND attempt_token = $2",
                    job_id,
                    attempt_token,
                )
                if existing is not None:
                    return SubmitResultOutcome(accepted=True, dedupe=True, record_count=existing["record_count"])

                try:
                    await conn.execute(
                        "INSERT INTO job_results (job_id, attempt_token, received_at, record_count) "
                        "VALUES ($1, $2, $3, $4)",
                        job_id,
                        attempt_token,
                        received_at,
                        len(certificates),
                    )
                except asyncpg.UniqueViolationError:
                    # Lost a race against a concurrent identical submission
                    # between the SELECT above and this INSERT - the other
                    # transaction's marker row now exists; treat exactly
                    # like the existing-row branch above rather than
                    # raising, since the semantics are the same either way.
                    existing = await conn.fetchrow(
                        "SELECT record_count FROM job_results WHERE job_id = $1 AND attempt_token = $2",
                        job_id,
                        attempt_token,
                    )
                    return SubmitResultOutcome(accepted=True, dedupe=True, record_count=existing["record_count"])

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
                    await conn.execute(
                        "INSERT INTO certificate_records "
                        "(record_id, job_id, attempt_token, tenant_id, target_id, plugin_id, plugin_version, "
                        "subject, issuer, serial_number, valid_from, valid_to, fingerprint, received_at) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
                        record.record_id,
                        record.job_id,
                        record.attempt_token,
                        record.tenant_id,
                        record.target_id,
                        record.plugin_id,
                        record.plugin_version,
                        record.subject,
                        record.issuer,
                        record.serial_number,
                        record.valid_from,
                        record.valid_to,
                        record.fingerprint,
                        record.received_at,
                    )
                    records.append(record)

        return SubmitResultOutcome(accepted=True, dedupe=False, record_count=len(records), records=tuple(records))

    async def list_by_tenant(self, tenant_id: str, *, limit: int) -> list[CertificateRecord]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM certificate_records WHERE tenant_id = $1 ORDER BY received_at DESC LIMIT $2",
                tenant_id,
                limit,
            )
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row) -> CertificateRecord:
        return CertificateRecord(
            record_id=row["record_id"],
            job_id=row["job_id"],
            attempt_token=row["attempt_token"],
            tenant_id=row["tenant_id"],
            target_id=row["target_id"],
            plugin_id=row["plugin_id"],
            plugin_version=row["plugin_version"],
            subject=row["subject"],
            issuer=row["issuer"],
            serial_number=row["serial_number"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            fingerprint=row["fingerprint"],
            received_at=row["received_at"],
        )
