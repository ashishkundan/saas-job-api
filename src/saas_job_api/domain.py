"""Internal job record model for the reference SaaS Job API store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    manifest_version: str
    priority: int
    scheduled_at: datetime
    correlation_id: str
    payload: dict[str, Any]
    max_attempts: int
    trace_id: str | None
    state: JobState = JobState.AVAILABLE

    receipt_token: str | None = None
    reserved_by: str | None = None
    reservation_until: datetime | None = None
    delivery_attempts: int = 0

    acknowledged_receipts: set[tuple[str, str]] = field(default_factory=set)
    ack_gateway_id: str | None = None
    ack_received_at: datetime | None = None
    ack_payload_hash: str | None = None
    ack_local_record_version: int | None = None

    def is_eligible(self, now: datetime) -> bool:
        if self.state == JobState.AVAILABLE:
            return True
        if self.state == JobState.RESERVED:
            return self.reservation_until is not None and self.reservation_until <= now
        return False
