"""In-memory Gateway operational configuration store."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from .gateway_operational_config import GatewayConfigTenantMismatch, GatewayOperationalConfig
from .gateway_operational_config_store_base import GatewayOperationalConfigStoreBase


@dataclass
class MemoryGatewayOperationalConfigStore(GatewayOperationalConfigStoreBase):
    _configs: dict[str, GatewayOperationalConfig] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get(self, gateway_id: str) -> GatewayOperationalConfig | None:
        async with self._lock:
            return self._configs.get(gateway_id)

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
        async with self._lock:
            previous = self._configs.get(gateway_id)
            if previous is not None and previous.tenant_id != tenant_id:
                raise GatewayConfigTenantMismatch(gateway_id)
            config = GatewayOperationalConfig(
                gateway_id=gateway_id,
                tenant_id=tenant_id,
                poll_interval_ms=poll_interval_ms,
                heartbeat_interval_ms=heartbeat_interval_ms,
                accept_new_jobs=accept_new_jobs,
                config_version=(previous.config_version if previous else 0) + 1,
                updated_at=updated_at,
            )
            self._configs[gateway_id] = config
            return config
