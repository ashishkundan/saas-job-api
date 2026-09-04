"""PostgreSQL-backed Target store."""

from __future__ import annotations

import asyncpg
from asyncpg import Pool

from .errors import NotFoundError
from .tenancy import Target
from .target_store_base import TargetStoreBase


class PostgresTargetStore(TargetStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def create(self, target: Target) -> Target:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO targets "
                    "(target_id, tenant_id, name, host, port, plugin_ref, plugin_version, credential_ref, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                    target.target_id,
                    target.tenant_id,
                    target.name,
                    target.host,
                    target.port,
                    target.plugin_ref,
                    target.plugin_version,
                    target.credential_ref,
                    target.created_at,
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"target_id already exists: {target.target_id}")
        return target

    async def get(self, tenant_id: str, target_id: str) -> Target | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM targets WHERE target_id = $1 AND tenant_id = $2", target_id, tenant_id
            )
        return self._row_to_target(row) if row is not None else None

    async def list_by_tenant(self, tenant_id: str) -> list[Target]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM targets WHERE tenant_id = $1 ORDER BY created_at", tenant_id)
        return [self._row_to_target(row) for row in rows]

    async def delete(self, tenant_id: str, target_id: str) -> None:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM targets WHERE target_id = $1 AND tenant_id = $2", target_id, tenant_id
            )
        if result == "DELETE 0":
            raise NotFoundError(f"target not found: {target_id}")

    @staticmethod
    def _row_to_target(row) -> Target:
        return Target(
            target_id=row["target_id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            host=row["host"],
            port=row["port"],
            plugin_ref=row["plugin_ref"],
            plugin_version=row["plugin_version"],
            credential_ref=row["credential_ref"],
            created_at=row["created_at"],
        )
