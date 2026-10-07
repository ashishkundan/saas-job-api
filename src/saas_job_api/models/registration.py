"""Request/response models for gateway registration and RBAC login."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EnrollmentTokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str  # plaintext - shown exactly once, never stored
    expires_at: datetime = Field(alias="expiresAt")


class EnrollmentTokenRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tenant_id: str | None = Field(default=None, alias="tenantId")


class GatewayRegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    enrollment_token: str = Field(alias="enrollmentToken")
    gateway_id: str = Field(alias="gatewayId")
    csr_pem: str = Field(alias="csrPem")


class GatewayRegisterResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    gateway_id: str = Field(alias="gatewayId")
    certificate_pem: str = Field(alias="certificatePem")
    ca_certificate_pem: str = Field(alias="caCertificatePem")
    not_after: datetime = Field(alias="notAfter")


class GatewayRegistrationStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    gateway_id: str = Field(alias="gatewayId")
    certificate_serial: str = Field(alias="certificateSerial")
    certificate_not_after: datetime = Field(alias="certificateNotAfter")
    registered_at: datetime = Field(alias="registeredAt")
    last_rotated_at: datetime = Field(alias="lastRotatedAt")


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # max_length=200 matches audit_events.actor (VARCHAR(200) NOT NULL,
    # see alembic/versions/006_audit_log.py) - a failed login writes
    # username there verbatim (routers/admin_auth.py), and an unbounded
    # username would reach that insert as a raw asyncpg error before the
    # intended 401 UnauthorizedError. Bounding it here rejects the
    # oversized request with a clean 400 instead.
    username: str = Field(max_length=200)
    password: str = Field(max_length=200)


class AdminLoginResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(alias="accessToken")
    token_type: str = Field(default="Bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    role: str
    tenant_id: str | None = Field(default=None, alias="tenantId")
