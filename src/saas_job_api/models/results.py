"""Request/response models for POST /gateway/v1/jobs/{jobId}/results (Phase 2.6)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CertificateRecordRequest(BaseModel):
    """Developer Implementation Guide §17/18 shape - the same fields the
    Gateway's plugin_orchestrator/schema.py already validates before this
    ever gets POSTed."""

    model_config = ConfigDict(populate_by_name=True)

    subject: str
    issuer: str
    serial_number: str = Field(alias="serialNumber")
    valid_from: datetime = Field(alias="validFrom")
    valid_to: datetime = Field(alias="validTo")
    fingerprint: str


class SubmitResultRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Optional cross-check against the path's {jobId} - HttpResultSink (2.4)
    # doesn't send it in the body today, only in the path, but a body copy
    # is accepted and validated if present.
    job_id: str | None = Field(default=None, alias="jobId")
    attempt_token: str = Field(alias="attemptToken")
    plugin_id: str = Field(alias="pluginId")
    plugin_version: str = Field(alias="pluginVersion")
    container_duration_ms: int | None = Field(default=None, alias="containerDurationMs")
    certificates: list[CertificateRecordRequest] = Field(default_factory=list)


class SubmitResultResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accepted: bool
    dedupe: bool
    record_count: int = Field(alias="recordCount")


class ReportInterruptedRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str | None = Field(default=None, alias="jobId")
    attempt_token: str = Field(alias="attemptToken")
