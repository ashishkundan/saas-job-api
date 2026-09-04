"""Request/response models for POST /gateway/v1/heartbeat (Phase 1.4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    gateway_id: str | None = Field(default=None, alias="gatewayId")
    status: str
    core_service: str = Field(alias="coreService")
    job_poller: str = Field(alias="jobPoller")
    plugin_orchestrator: str = Field(alias="pluginOrchestrator")
    container_runtime: str = Field(alias="containerRuntime")
    cpu_usage: float = Field(alias="cpuUsage")
    memory_usage: float = Field(alias="memoryUsage")
    disk_usage: float = Field(alias="diskUsage")
    timestamp: datetime
    gateway_version: str | None = Field(default=None, alias="gatewayVersion")


class HeartbeatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    gateway_id: str = Field(alias="gatewayId")
    current_status: str = Field(alias="currentStatus")
