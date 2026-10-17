"""Admin/test-only request models for seeding jobs and injecting faults."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminCreateJobRequest(BaseModel):
    """A job is always created for one tenant's managed Target. The
    execution payload (pluginRef, pluginVersion, targetEndpoint,
    credentialRef) is derived from that Target, never accepted from the
    caller - extra="forbid" rejects a free-form `payload` with 422."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tenant_id: str = Field(alias="tenantId", min_length=1, max_length=50)
    target_id: str = Field(alias="targetId", min_length=1, max_length=50)
    job_id: str | None = Field(default=None, alias="jobId")
    # Defaults to "<pluginRef>-scan" from the Target; if given it must match.
    job_type: str | None = Field(default=None, alias="jobType")
    manifest_version: str = Field(default="1.0", alias="manifestVersion")
    priority: int = 50
    scheduled_at: datetime | None = Field(default=None, alias="scheduledAt")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds", ge=1, le=3600)
    max_attempts: int = Field(default=8, alias="maxAttempts")
    trace_id: str | None = Field(default=None, alias="traceId")


class FaultInjectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    next_poll_status: int = Field(alias="nextPollStatus")
    retry_after_seconds: float | None = Field(default=None, alias="retryAfterSeconds")
