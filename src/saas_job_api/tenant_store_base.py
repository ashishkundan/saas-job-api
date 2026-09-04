"""Abstract base class for Tenant storage (Phase 2.5)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .tenancy import Tenant


class TenantStoreBase(ABC):
    @abstractmethod
    async def create(self, tenant: Tenant) -> Tenant:
        """Persist a new tenant. Raise ValueError if tenant_id already exists."""

    @abstractmethod
    async def get(self, tenant_id: str) -> Tenant | None:
        """Look up one tenant by id."""

    @abstractmethod
    async def list_all(self) -> list[Tenant]:
        """Return every tenant (platform_admin fleet view)."""

    @abstractmethod
    async def delete(self, tenant_id: str) -> None:
        """Remove one tenant. Raise NotFoundError if it doesn't exist."""
