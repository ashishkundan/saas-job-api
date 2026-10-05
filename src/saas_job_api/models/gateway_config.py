"""Models for Gateway operational configuration."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..gateway_operational_config import (
    MAX_HEARTBEAT_INTERVAL_MS,
    MAX_POLL_INTERVAL_MS,
    MIN_HEARTBEAT_INTERVAL_MS,
    MIN_POLL_INTERVAL_MS,
)


class GatewayOperationalConfigUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    poll_interval_ms: int = Field(
        alias="pollIntervalMs",
        ge=MIN_POLL_INTERVAL_MS,
        le=MAX_POLL_INTERVAL_MS,
    )
    heartbeat_interval_ms: int = Field(
        alias="heartbeatIntervalMs",
        ge=MIN_HEARTBEAT_INTERVAL_MS,
        le=MAX_HEARTBEAT_INTERVAL_MS,
    )
    accept_new_jobs: bool = Field(alias="acceptNewJobs")


class GatewayOperationalConfigResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(alias="schemaVersion")
    config_version: int = Field(alias="configVersion")
    poll_interval_ms: int = Field(alias="pollIntervalMs")
    heartbeat_interval_ms: int = Field(alias="heartbeatIntervalMs")
    accept_new_jobs: bool = Field(alias="acceptNewJobs")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
