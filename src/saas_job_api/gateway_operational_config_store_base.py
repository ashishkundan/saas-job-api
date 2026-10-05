"""Storage interface for per-Gateway operational configuration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .gateway_operational_config import GatewayOperationalConfig


class GatewayOperationalConfigStoreBase(ABC):
    @abstractmethod
    async def get(self, gateway_id: str) -> GatewayOperationalConfig | None:
        """Return one Gateway's config, if explicitly configured."""

    @abstractmethod
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
        """Create or update config without changing its tenant assignment."""
