"""Domain types for gateway registration (mTLS) and admin RBAC (Phase 1.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AdminRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    TENANT_VIEWER = "tenant_viewer"


@dataclass(slots=True)
class EnrollmentToken:
    """A one-time token authorizing exactly one gateway registration.

    Only token_hash (sha256 of the plaintext) is ever persisted - the
    plaintext token is returned once, at issuance, and never stored.
    """

    token_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    issued_by: str | None = None
    used_at: datetime | None = None
    used_by_gateway_id: str | None = None

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(slots=True)
class GatewayIdentity:
    """The currently-valid mTLS identity issued to one gateway."""

    gateway_id: str
    public_key_fingerprint: str
    certificate_pem: str
    certificate_serial: str
    certificate_not_after: datetime
    registered_at: datetime
    last_rotated_at: datetime
    tenant_id: str | None = None


@dataclass(slots=True)
class AdminPrincipal:
    """A human/service account authenticating to the admin/platform API."""

    principal_id: str
    username: str
    password_hash: str
    role: AdminRole
    created_at: datetime
