"""Append-only audit log (Phase 2.7).

Append-only is enforced by the store interface itself, not by convention:
AuditLogStoreBase declares append() and list_recent() only - there is no
update/delete method anywhere in the interface for an implementation (or
a caller) to even call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    # gateway_id for a gateway-initiated event, a principal's username for
    # an admin-initiated one, "system" for something no caller triggered.
    actor: str
    tenant_id: str | None
    resource_type: str | None
    resource_id: str | None
    detail: dict[str, Any]
    occurred_at: datetime


async def record_audit_event(
    store: Any,  # AuditLogStoreBase - not imported here to avoid a cycle (it imports AuditEvent from this module)
    *,
    event_type: str,
    actor: str,
    now: datetime,
    tenant_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    """One-line helper so every call site (registration.py, tenants.py,
    targets.py, schedules.py, results.py, admin_auth.py) looks the same
    rather than each hand-constructing an AuditEvent + calling append()."""

    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        actor=actor,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail or {},
        occurred_at=now,
    )
    return await store.append(event)
