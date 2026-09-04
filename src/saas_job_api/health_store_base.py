"""Abstract base class for GatewayStatus storage."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .health import GatewayStatus


class HealthStoreBase(ABC):
    @abstractmethod
    async def upsert(self, status: GatewayStatus) -> GatewayStatus:
        """Insert or replace one gateway's status record."""

    @abstractmethod
    async def get(self, gateway_id: str) -> GatewayStatus | None:
        """Return the stored status record for one gateway, if any."""

    @abstractmethod
    async def list_all(self) -> list[GatewayStatus]:
        """Return all stored status records (fleet view, Phase 3.2)."""
