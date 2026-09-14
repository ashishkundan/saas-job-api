"""Response model for GET /admin/v1/audit (Phase 2.7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    event_type: str = Field(alias="eventType")
    actor: str
    tenant_id: str | None = Field(default=None, alias="tenantId")
    resource_type: str | None = Field(default=None, alias="resourceType")
    resource_id: str | None = Field(default=None, alias="resourceId")
    detail: dict[str, Any]
    occurred_at: datetime = Field(alias="occurredAt")
