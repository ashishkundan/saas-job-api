"""Request/response models for POST /gateway/v1/jobs/{jobId}/received (TDD §9.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ReceivedRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # DEPRECATED (Phase 0.1, 2026-09-04): only used by the deprecated legacy
    # flat-body alias route (POST /gateway/v1/jobs/received). The current
    # client always path-templates {jobId} and never sends it in the body.
    job_id: str | None = Field(default=None, alias="jobId")
    gateway_id: str | None = Field(default=None, alias="gatewayId")
    receipt_token: str = Field(alias="receiptToken")
    # DEPRECATED (Phase 0.1, 2026-09-04): "acknowledgedAt" was accepted because
    # the older client sent that name instead of the TDD's "receivedAt". The
    # current client sends only "receivedAt"; this alias is kept for any
    # already-deployed older client and is scheduled for removal in Phase 4.
    received_at: datetime = Field(validation_alias=AliasChoices("receivedAt", "acknowledgedAt"))
    payload_hash: str | None = Field(default=None, alias="payloadHash")
    local_record_version: int | None = Field(default=None, alias="localRecordVersion")


class ReceivedResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: Literal["ACKNOWLEDGED"] = "ACKNOWLEDGED"
