"""PostgreSQL-backed GatewayStatus store."""

from __future__ import annotations

from asyncpg import Pool

from .health import GatewayStatus, HealthState
from .health_store_base import HealthStoreBase


class PostgresHealthStore(HealthStoreBase):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def upsert(self, status: GatewayStatus) -> GatewayStatus:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO gateway_status "
                "(gateway_id, tenant_id, last_heartbeat_at, gateway_version, container_runtime_status, "
                "last_successful_job_at, last_error, last_reported_status) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (gateway_id) DO UPDATE SET "
                "tenant_id = EXCLUDED.tenant_id, "
                "last_heartbeat_at = EXCLUDED.last_heartbeat_at, "
                "gateway_version = EXCLUDED.gateway_version, "
                "container_runtime_status = EXCLUDED.container_runtime_status, "
                "last_successful_job_at = EXCLUDED.last_successful_job_at, "
                "last_error = EXCLUDED.last_error, "
                "last_reported_status = EXCLUDED.last_reported_status",
                status.gateway_id,
                status.tenant_id,
                status.last_heartbeat_at,
                status.gateway_version,
                status.container_runtime_status,
                status.last_successful_job_at,
                status.last_error,
                status.last_reported_status.value if status.last_reported_status else None,
            )
        return status

    async def get(self, gateway_id: str) -> GatewayStatus | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM gateway_status WHERE gateway_id = $1", gateway_id)
        return self._row_to_status(row) if row is not None else None

    async def list_all(self) -> list[GatewayStatus]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM gateway_status ORDER BY gateway_id")
        return [self._row_to_status(row) for row in rows]

    @staticmethod
    def _row_to_status(row) -> GatewayStatus:
        return GatewayStatus(
            gateway_id=row["gateway_id"],
            tenant_id=row["tenant_id"],
            last_heartbeat_at=row["last_heartbeat_at"],
            gateway_version=row["gateway_version"],
            container_runtime_status=row["container_runtime_status"],
            last_successful_job_at=row["last_successful_job_at"],
            last_error=row["last_error"],
            last_reported_status=HealthState(row["last_reported_status"]) if row["last_reported_status"] else None,
        )
