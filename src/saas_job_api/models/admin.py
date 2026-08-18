"""Admin/test-only request models for seeding jobs and injecting faults."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdminCreateJobRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str | None = Field(default=None, alias="jobId")
    job_type: str = Field(alias="jobType")
    manifest_version: str = Field(alias="manifestVersion")
    priority: int = 50
    scheduled_at: datetime | None = Field(default=None, alias="scheduledAt")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=8, alias="maxAttempts")
    trace_id: str | None = Field(default=None, alias="traceId")


class FaultInjectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    next_poll_status: int = Field(alias="nextPollStatus")
    retry_after_seconds: float | None = Field(default=None, alias="retryAfterSeconds")
