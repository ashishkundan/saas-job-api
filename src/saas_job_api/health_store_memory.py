"""In-memory GatewayStatus store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .health import GatewayStatus
from .health_store_base import HealthStoreBase


@dataclass
class MemoryHealthStore(HealthStoreBase):
    _statuses: dict[str, GatewayStatus] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def upsert(self, status: GatewayStatus) -> GatewayStatus:
        async with self._lock:
            self._statuses[status.gateway_id] = status
            return status

    async def get(self, gateway_id: str) -> GatewayStatus | None:
        async with self._lock:
            return self._statuses.get(gateway_id)

    async def list_all(self) -> list[GatewayStatus]:
        async with self._lock:
            return list(self._statuses.values())
