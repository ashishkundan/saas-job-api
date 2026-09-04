"""Request/response models for gateway registration and RBAC login."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EnrollmentTokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str  # plaintext - shown exactly once, never stored
    expires_at: datetime = Field(alias="expiresAt")


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

    username: str
    password: str


class AdminLoginResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(alias="accessToken")
    token_type: str = Field(default="Bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    role: str
    tenant_id: str | None = Field(default=None, alias="tenantId")
