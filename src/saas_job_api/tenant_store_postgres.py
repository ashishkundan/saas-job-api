"""PostgreSQL-backed Tenant store."""

from __future__ import annotations

import asyncpg
from asyncpg import Pool

from .errors import NotFoundError
from .tenancy import Tenant
from .tenant_store_base import TenantStoreBase


class PostgresTenantStore(TenantStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def create(self, tenant: Tenant) -> Tenant:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO tenants (tenant_id, name, created_at, is_active) VALUES ($1, $2, $3, $4)",
                    tenant.tenant_id,
                    tenant.name,
                    tenant.created_at,
                    tenant.is_active,
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"tenant_id already exists: {tenant.tenant_id}")
        return tenant

    async def get(self, tenant_id: str) -> Tenant | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tenants WHERE tenant_id = $1", tenant_id)
        return self._row_to_tenant(row) if row is not None else None

    async def list_all(self) -> list[Tenant]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM tenants ORDER BY created_at")
        return [self._row_to_tenant(row) for row in rows]

    async def delete(self, tenant_id: str) -> None:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM tenants WHERE tenant_id = $1", tenant_id)
        if result == "DELETE 0":
            raise NotFoundError(f"tenant not found: {tenant_id}")

    @staticmethod
    def _row_to_tenant(row) -> Tenant:
        return Tenant(
            tenant_id=row["tenant_id"],
            name=row["name"],
            created_at=row["created_at"],
            is_active=row["is_active"],
        )
