"""Storage interface for per-Gateway operational configuration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable

from .audit import AuditEvent
from .audit_store_base import AuditLogStoreBase
from .gateway_operational_config import GatewayOperationalConfig

GatewayConfigAuditFactory = Callable[
    [GatewayOperationalConfig | None, GatewayOperationalConfig],
    AuditEvent,
]


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

    @abstractmethod
    async def save_with_previous(
        self,
        *,
        gateway_id: str,
        tenant_id: str,
        poll_interval_ms: int,
        heartbeat_interval_ms: int,
        accept_new_jobs: bool,
        updated_at: datetime,
        audit_store: AuditLogStoreBase | None = None,
        audit_event_factory: GatewayConfigAuditFactory | None = None,
    ) -> tuple[GatewayOperationalConfig | None, GatewayOperationalConfig]:
        """Persist a versioned update and optional audit event atomically."""
