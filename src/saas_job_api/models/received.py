"""Request/response models for POST /gateway/v1/jobs/{jobId}/received (TDD §9.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ReceivedRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Only required/used by the legacy flat-body alias route (POST /gateway/v1/jobs/received),
    # since the current client always sends jobId in the body, never as a path parameter.
    job_id: str | None = Field(default=None, alias="jobId")
    gateway_id: str | None = Field(default=None, alias="gatewayId")
    receipt_token: str = Field(alias="receiptToken")
    # Accepts "acknowledgedAt" too: the current client sends that name instead of
    # the TDD's "receivedAt". See saas-job-api/README.md "Known contract gaps".
    received_at: datetime = Field(validation_alias=AliasChoices("receivedAt", "acknowledgedAt"))
    payload_hash: str | None = Field(default=None, alias="payloadHash")
    local_record_version: int | None = Field(default=None, alias="localRecordVersion")


class ReceivedResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: Literal["ACKNOWLEDGED"] = "ACKNOWLEDGED"
