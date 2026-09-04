"""Request/response models for Tenant / Target / Schedule (Phase 2.5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str | None = Field(default=None, alias="tenantId")
    name: str


class TenantResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(alias="tenantId")
    name: str
    created_at: datetime = Field(alias="createdAt")
    is_active: bool = Field(alias="isActive")


class TargetCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_id: str | None = Field(default=None, alias="targetId")
    name: str
    host: str
    port: int
    plugin_ref: str = Field(alias="pluginRef")
    plugin_version: str = Field(alias="pluginVersion")
    credential_ref: str | None = Field(default=None, alias="credentialRef")


class TargetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_id: str = Field(alias="targetId")
    tenant_id: str = Field(alias="tenantId")
    name: str
    host: str
    port: int
    plugin_ref: str = Field(alias="pluginRef")
    plugin_version: str = Field(alias="pluginVersion")
    credential_ref: str | None = Field(default=None, alias="credentialRef")
    created_at: datetime = Field(alias="createdAt")


class ScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schedule_id: str | None = Field(default=None, alias="scheduleId")
    target_id: str = Field(alias="targetId")
    job_type: str = Field(alias="jobType")
    manifest_version: str = Field(alias="manifestVersion")
    interval_seconds: int = Field(alias="intervalSeconds")
    # Defaults to "due immediately" (now) if omitted - main.py's clock
    # provides "now" at request-handling time, not import time.
    next_run_at: datetime | None = Field(default=None, alias="nextRunAt")


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schedule_id: str = Field(alias="scheduleId")
    tenant_id: str = Field(alias="tenantId")
    target_id: str = Field(alias="targetId")
    job_type: str = Field(alias="jobType")
    manifest_version: str = Field(alias="manifestVersion")
    interval_seconds: int = Field(alias="intervalSeconds")
    next_run_at: datetime = Field(alias="nextRunAt")
    enabled: bool
    last_run_at: datetime | None = Field(default=None, alias="lastRunAt")
    created_at: datetime = Field(alias="createdAt")
