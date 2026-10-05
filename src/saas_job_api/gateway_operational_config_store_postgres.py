"""PostgreSQL-backed Gateway operational configuration store."""

from __future__ import annotations

from datetime import datetime

from asyncpg import Pool

from .gateway_operational_config import GatewayConfigTenantMismatch, GatewayOperationalConfig
from .gateway_operational_config_store_base import GatewayOperationalConfigStoreBase


class PostgresGatewayOperationalConfigStore(GatewayOperationalConfigStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def get(self, gateway_id: str) -> GatewayOperationalConfig | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gateway_operational_configs WHERE gateway_id = $1",
                gateway_id,
            )
        return self._row_to_config(row) if row is not None else None

    async def save(
        self,
        *,
        gateway_id: str,
        tenant_id: str,
        poll_interval_ms: int,
        heartbeat_interval_ms: int,
        accept_new_jobs: bool,
        updated_at: datetime,
    ) -> GatewayOperationalConfig:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO gateway_operational_configs "
                "(gateway_id, tenant_id, poll_interval_ms, heartbeat_interval_ms, "
                "accept_new_jobs, config_version, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, 1, $6) "
                "ON CONFLICT (gateway_id) DO UPDATE SET "
                "poll_interval_ms = EXCLUDED.poll_interval_ms, "
                "heartbeat_interval_ms = EXCLUDED.heartbeat_interval_ms, "
                "accept_new_jobs = EXCLUDED.accept_new_jobs, "
                "config_version = gateway_operational_configs.config_version + 1, "
                "updated_at = EXCLUDED.updated_at "
                "WHERE gateway_operational_configs.tenant_id = EXCLUDED.tenant_id "
                "RETURNING *",
                gateway_id,
                tenant_id,
                poll_interval_ms,
                heartbeat_interval_ms,
                accept_new_jobs,
                updated_at,
            )
        if row is None:
            raise GatewayConfigTenantMismatch(gateway_id)
        return self._row_to_config(row)

    @staticmethod
    def _row_to_config(row) -> GatewayOperationalConfig:
        return GatewayOperationalConfig(
            gateway_id=row["gateway_id"],
            tenant_id=row["tenant_id"],
            poll_interval_ms=row["poll_interval_ms"],
            heartbeat_interval_ms=row["heartbeat_interval_ms"],
            accept_new_jobs=row["accept_new_jobs"],
            config_version=row["config_version"],
            updated_at=row["updated_at"],
        )
