"""In-memory registration store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from .identity import EnrollmentToken, GatewayIdentity
from .registration_store_base import RegistrationStoreBase


@dataclass
class MemoryRegistrationStore(RegistrationStoreBase):
    _tokens_by_hash: dict[str, EnrollmentToken] = field(default_factory=dict)
    _identities: dict[str, GatewayIdentity] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def create_enrollment_token(self, token: EnrollmentToken) -> EnrollmentToken:
        async with self._lock:
            self._tokens_by_hash[token.token_hash] = token
            return token

    async def get_enrollment_token_by_hash(self, token_hash: str) -> EnrollmentToken | None:
        async with self._lock:
            return self._tokens_by_hash.get(token_hash)

    async def mark_enrollment_token_used(self, token_id: str, *, used_at: datetime, gateway_id: str) -> None:
        async with self._lock:
            for token in self._tokens_by_hash.values():
                if token.token_id == token_id:
                    token.used_at = used_at
                    token.used_by_gateway_id = gateway_id
                    return

    async def upsert_gateway_identity(self, identity: GatewayIdentity) -> GatewayIdentity:
        async with self._lock:
            self._identities[identity.gateway_id] = identity
            return identity

    async def get_gateway_identity(self, gateway_id: str) -> GatewayIdentity | None:
        async with self._lock:
            return self._identities.get(gateway_id)
