"""GET /admin/v1/audit (Phase 2.7) - platform_admin only. A tenant_admin/
tenant_viewer has no access at all here, not even scoped to their own
tenant - the audit log itself is a platform-level security surface, per
the plan's "GET /admin/v1/audit (platform_admin only)"."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..audit_store_base import AuditLogStoreBase
from ..auth import require_role
from ..identity import AdminRole
from ..models.audit import AuditEventResponse

router = APIRouter(prefix="/admin/v1/audit", tags=["audit"])


def get_audit_store(request: Request) -> AuditLogStoreBase:
    return request.app.state.audit_store


@router.get("", response_model=list[AuditEventResponse])
async def list_audit_events(
    tenant_id: str | None = Query(default=None, alias="tenantId"),
    limit: int = 100,
    store: AuditLogStoreBase = Depends(get_audit_store),
    _claims=Depends(require_role(AdminRole.PLATFORM_ADMIN)),
) -> list[AuditEventResponse]:
    events = await store.list_recent(tenant_id=tenant_id, limit=limit)
    return [
        AuditEventResponse(
            eventId=e.event_id,
            eventType=e.event_type,
            actor=e.actor,
            tenantId=e.tenant_id,
            resourceType=e.resource_type,
            resourceId=e.resource_id,
            detail=e.detail,
            occurredAt=e.occurred_at,
        )
        for e in events
    ]
