"""Abstract base class for gateway registration (enrollment tokens + identities)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .identity import EnrollmentToken, GatewayIdentity


class RegistrationStoreBase(ABC):
    """Abstract interface for enrollment-token and gateway-identity storage."""

    @abstractmethod
    async def create_enrollment_token(self, token: EnrollmentToken) -> EnrollmentToken:
        """Persist a newly-issued enrollment token."""

    @abstractmethod
    async def get_enrollment_token_by_hash(self, token_hash: str) -> EnrollmentToken | None:
        """Look up an enrollment token by the hash of its plaintext value."""

    @abstractmethod
    async def mark_enrollment_token_used(self, token_id: str, *, used_at: datetime, gateway_id: str) -> None:
        """Mark a token consumed. Idempotent re-registration re-checks is_used first."""

    @abstractmethod
    async def upsert_gateway_identity(self, identity: GatewayIdentity) -> GatewayIdentity:
        """Insert or replace the current identity/certificate for a gateway (rotation)."""

    @abstractmethod
    async def get_gateway_identity(self, gateway_id: str) -> GatewayIdentity | None:
        """Return the current identity/certificate for one gateway, if registered."""
