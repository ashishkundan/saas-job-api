"""In-memory Tenant store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .errors import NotFoundError
from .tenancy import Tenant
from .tenant_store_base import TenantStoreBase


@dataclass
class MemoryTenantStore(TenantStoreBase):
    _tenants: dict[str, Tenant] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def create(self, tenant: Tenant) -> Tenant:
        async with self._lock:
            if tenant.tenant_id in self._tenants:
                raise ValueError(f"tenant_id already exists: {tenant.tenant_id}")
            self._tenants[tenant.tenant_id] = tenant
            return tenant

    async def get(self, tenant_id: str) -> Tenant | None:
        async with self._lock:
            return self._tenants.get(tenant_id)

    async def list_all(self) -> list[Tenant]:
        async with self._lock:
            return list(self._tenants.values())

    async def delete(self, tenant_id: str) -> None:
        async with self._lock:
            if tenant_id not in self._tenants:
                raise NotFoundError(f"tenant not found: {tenant_id}")
            del self._tenants[tenant_id]
