"""Request/response models for Tenant / Target / Schedule (Phase 2.5)."""

from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    # Omit to follow the tenant's pinned version of the plugin.
    plugin_version: str | None = Field(default=None, alias="pluginVersion", pattern=r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
    credential_ref: str | None = Field(default=None, alias="credentialRef")


class TargetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_id: str = Field(alias="targetId")
    tenant_id: str = Field(alias="tenantId")
    name: str
    host: str
    port: int
    plugin_ref: str = Field(alias="pluginRef")
    # The target's own override (None = follows the tenant pin) and the
    # version its jobs actually run (None = no version: jobs are refused).
    plugin_version: str | None = Field(alias="pluginVersion")
    effective_plugin_version: str | None = Field(alias="effectivePluginVersion")
    credential_ref: str | None = Field(default=None, alias="credentialRef")
    created_at: datetime = Field(alias="createdAt")


class TargetBulkCreateRequest(BaseModel):
    """One server, many ports: one Target per port, id "<serverId>-<port>"."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # 44 + "-" + 5 port digits stays within the 50-character target_id column.
    server_id: str = Field(alias="serverId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,43}$")
    name: str | None = None  # default: serverId; each target is "<name> port <port>"
    host: str = Field(min_length=1, max_length=253)
    ports: list[int] = Field(min_length=1, max_length=1024)
    plugin_ref: str = Field(alias="pluginRef")
    plugin_version: str | None = Field(default=None, alias="pluginVersion", pattern=r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
    credential_ref: str | None = Field(default=None, alias="credentialRef")

    @field_validator("ports")
    @classmethod
    def _valid_unique_ports(cls, ports: list[int]) -> list[int]:
        bad = [p for p in ports if not 1 <= p <= 65535]
        if bad:
            raise ValueError(f"ports must be 1-65535: {bad}")
        if len(set(ports)) != len(ports):
            raise ValueError("ports must be unique")
        return ports


class TargetBulkResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    port: int
    target_id: str = Field(alias="targetId")
    # created: new target. exists: identical target already there (no change).
    # conflict: a target with this id exists with different settings (no change).
    status: Literal["created", "exists", "conflict"]
    detail: str | None = None


class TargetBulkCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_id: str = Field(alias="serverId")
    created: int
    existing: int
    conflicts: int
    results: list[TargetBulkResult]


class PluginEntitlementRequest(BaseModel):
    """Optional body of PUT /admin/v1/tenants/{tenantId}/plugins/{pluginRef}.
    "version" pins the tenant's default version of the plugin (null removes
    the pin); "resetTargetOverrides" moves every target of that plugin onto
    the pin, e.g. to upgrade or roll back a customer in one step."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    version: str | None = Field(default=None, pattern=r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
    reset_target_overrides: bool = Field(default=False, alias="resetTargetOverrides")


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
