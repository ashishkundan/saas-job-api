"""In-memory RBAC (admin principal) store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .identity import AdminPrincipal
from .rbac_store_base import RbacStoreBase


@dataclass
class MemoryRbacStore(RbacStoreBase):
    _principals_by_username: dict[str, AdminPrincipal] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def create_principal(self, principal: AdminPrincipal) -> AdminPrincipal:
        async with self._lock:
            if principal.username in self._principals_by_username:
                raise ValueError(f"username already exists: {principal.username}")
            self._principals_by_username[principal.username] = principal
            return principal

    async def get_by_username(self, username: str) -> AdminPrincipal | None:
        async with self._lock:
            return self._principals_by_username.get(username)
