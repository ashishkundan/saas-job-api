"""PostgreSQL-backed RBAC (admin principal) store."""

from __future__ import annotations

import asyncpg
from asyncpg import Pool

from .identity import AdminPrincipal, AdminRole
from .rbac_store_base import RbacStoreBase


class PostgresRbacStore(RbacStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def create_principal(self, principal: AdminPrincipal) -> AdminPrincipal:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO admin_principals (principal_id, username, password_hash, role, created_at, tenant_id) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    principal.principal_id,
                    principal.username,
                    principal.password_hash,
                    principal.role.value,
                    principal.created_at,
                    principal.tenant_id,
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"username already exists: {principal.username}")
        return principal

    async def get_by_username(self, username: str) -> AdminPrincipal | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM admin_principals WHERE username = $1", username)
        if row is None:
            return None
        return AdminPrincipal(
            principal_id=row["principal_id"],
            username=row["username"],
            password_hash=row["password_hash"],
            role=AdminRole(row["role"]),
            created_at=row["created_at"],
            tenant_id=row["tenant_id"],
        )
