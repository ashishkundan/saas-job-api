"""PostgreSQL-backed registration store (enrollment tokens + gateway identities)."""

from __future__ import annotations

from datetime import datetime

from asyncpg import Pool

from .identity import EnrollmentToken, GatewayIdentity
from .registration_store_base import RegistrationStoreBase


class PostgresRegistrationStore(RegistrationStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def create_enrollment_token(self, token: EnrollmentToken) -> EnrollmentToken:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO enrollment_tokens "
                "(token_id, token_hash, created_at, expires_at, issued_by, used_at, used_by_gateway_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                token.token_id,
                token.token_hash,
                token.created_at,
                token.expires_at,
                token.issued_by,
                token.used_at,
                token.used_by_gateway_id,
            )
        return token

    async def get_enrollment_token_by_hash(self, token_hash: str) -> EnrollmentToken | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM enrollment_tokens WHERE token_hash = $1", token_hash)
        return self._row_to_token(row) if row is not None else None

    async def mark_enrollment_token_used(self, token_id: str, *, used_at: datetime, gateway_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE enrollment_tokens SET used_at = $1, used_by_gateway_id = $2 WHERE token_id = $3",
                used_at,
                gateway_id,
                token_id,
            )

    async def upsert_gateway_identity(self, identity: GatewayIdentity) -> GatewayIdentity:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO gateway_identities "
                "(gateway_id, tenant_id, public_key_fingerprint, certificate_pem, certificate_serial, "
                "certificate_not_after, registered_at, last_rotated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (gateway_id) DO UPDATE SET "
                "public_key_fingerprint = EXCLUDED.public_key_fingerprint, "
                "certificate_pem = EXCLUDED.certificate_pem, "
                "certificate_serial = EXCLUDED.certificate_serial, "
                "certificate_not_after = EXCLUDED.certificate_not_after, "
                "last_rotated_at = EXCLUDED.last_rotated_at",
                identity.gateway_id,
                identity.tenant_id,
                identity.public_key_fingerprint,
                identity.certificate_pem,
                identity.certificate_serial,
                identity.certificate_not_after,
                identity.registered_at,
                identity.last_rotated_at,
            )
        return identity

    async def get_gateway_identity(self, gateway_id: str) -> GatewayIdentity | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM gateway_identities WHERE gateway_id = $1", gateway_id)
        return self._row_to_identity(row) if row is not None else None

    @staticmethod
    def _row_to_token(row) -> EnrollmentToken:
        return EnrollmentToken(
            token_id=row["token_id"],
            token_hash=row["token_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            issued_by=row["issued_by"],
            used_at=row["used_at"],
            used_by_gateway_id=row["used_by_gateway_id"],
        )

    @staticmethod
    def _row_to_identity(row) -> GatewayIdentity:
        return GatewayIdentity(
            gateway_id=row["gateway_id"],
            tenant_id=row["tenant_id"],
            public_key_fingerprint=row["public_key_fingerprint"],
            certificate_pem=row["certificate_pem"],
            certificate_serial=row["certificate_serial"],
            certificate_not_after=row["certificate_not_after"],
            registered_at=row["registered_at"],
            last_rotated_at=row["last_rotated_at"],
        )
