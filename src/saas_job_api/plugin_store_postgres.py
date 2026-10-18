"""PostgreSQL-backed plugin distribution store."""

from __future__ import annotations

import hashlib
from datetime import datetime

from asyncpg import Pool

from .plugin_store_base import PluginStoreBase


class PostgresPluginStore(PluginStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def put_repo_file(self, kind: str, path: str, content: bytes, *, now: datetime) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO plugin_repo_files (kind, path, content, sha256, updated_at) VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (kind, path) DO UPDATE SET content = EXCLUDED.content, sha256 = EXCLUDED.sha256, "
                "updated_at = EXCLUDED.updated_at",
                kind, path, content, hashlib.sha256(content).hexdigest(), now,
            )

    async def get_repo_file(self, kind: str, path: str) -> bytes | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT content FROM plugin_repo_files WHERE kind = $1 AND path = $2", kind, path)
        return bytes(row["content"]) if row is not None else None

    async def grant(self, tenant_id: str, plugin_ref: str, *, now: datetime) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "INSERT INTO tenant_plugins (tenant_id, plugin_ref, created_at) VALUES ($1, $2, $3) "
                "ON CONFLICT (tenant_id, plugin_ref) DO NOTHING",
                tenant_id, plugin_ref, now,
            )
        return result == "INSERT 0 1"

    async def revoke(self, tenant_id: str, plugin_ref: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM tenant_plugins WHERE tenant_id = $1 AND plugin_ref = $2", tenant_id, plugin_ref
            )
        return result == "DELETE 1"

    async def list_plugins(self, tenant_id: str) -> list[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT plugin_ref FROM tenant_plugins WHERE tenant_id = $1 ORDER BY plugin_ref", tenant_id
            )
        return [row["plugin_ref"] for row in rows]

    async def is_entitled(self, tenant_id: str, plugin_ref: str) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM tenant_plugins WHERE tenant_id = $1 AND plugin_ref = $2", tenant_id, plugin_ref
            )
        return row is not None
