"""Request/response models for POST /gateway/v1/jobs/poll (TDD §9.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PollRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    request_id: str | None = Field(default=None, alias="requestId")
    gateway_id: str | None = Field(default=None, alias="gatewayId")
    max_jobs: int = Field(default=20, alias="maxJobs", ge=1, le=200)
    supported_job_types: list[str] | None = Field(default=None, alias="supportedJobTypes")
    supported_manifest_versions: list[str] | None = Field(default=None, alias="supportedManifestVersions")
    available_dispatch_slots: int | None = Field(default=None, alias="availableDispatchSlots")
    client_time: datetime | None = Field(default=None, alias="clientTime")


class Job(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    job_type: str = Field(alias="jobType")
    manifest_version: str = Field(alias="manifestVersion")
    priority: int = 50
    scheduled_at: datetime = Field(alias="scheduledAt")
    receipt_token: str = Field(alias="receiptToken")
    correlation_id: str = Field(alias="correlationId")
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=8, alias="maxAttempts")
    trace_id: str | None = Field(default=None, alias="traceId")
    payload_hash: str | None = Field(default=None, alias="payloadHash")


class PollResponse(BaseModel):
    """`received_at` mirrors `server_time` as a compatibility shim: the parent
    repo's HttpJobSource.poll() unconditionally requires a `receivedAt` key
    and raises otherwise. This is not part of TDD §9.1; see saas-job-api/README.md
    "Known contract gaps"."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    server_time: datetime = Field(alias="serverTime")
    received_at: datetime = Field(alias="receivedAt")
    poll_after_ms: int = Field(alias="pollAfterMs")
    reservation_until: datetime | None = Field(default=None, alias="reservationUntil")
    jobs: list[Job] = Field(default_factory=list)
