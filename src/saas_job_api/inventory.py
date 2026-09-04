"""Certificate inventory domain types (Phase 2.6).

Two tables, not one: `job_results` is a bare (job_id, attempt_token)
idempotency marker with a DB-level unique constraint - the literal
requirement from the plan ("unique constraint on (job_id, attempt_token)
enforcing idempotency") - while `certificate_records` is the actual,
queryable inventory (one row per certificate, tagged with tenant_id/
target_id for cross-tenant isolation). Submitting a result inserts into
both, in one transaction, gated by the marker: a duplicate/retried
submission for the same (job_id, attempt_token) is detected via the
marker and never touches certificate_records again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class CertificateRecord:
    record_id: str
    job_id: str
    attempt_token: str
    tenant_id: str | None
    target_id: str | None
    plugin_id: str
    plugin_version: str
    subject: str
    issuer: str
    serial_number: str
    valid_from: datetime
    valid_to: datetime
    fingerprint: str
    received_at: datetime


@dataclass(slots=True, frozen=True)
class SubmitResultOutcome:
    accepted: bool
    dedupe: bool
    record_count: int
    records: tuple[CertificateRecord, ...] = field(default_factory=tuple)
