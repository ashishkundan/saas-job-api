"""Abstract base class for Target storage (Phase 2.5).

Reads/deletes take tenant_id alongside the target_id as a second, defense-
in-depth scoping layer - even if a router's RBAC check were ever wrong, a
store call scoped to the wrong tenant_id simply finds nothing, rather than
returning or deleting another tenant's Target.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .tenancy import Target


class TargetStoreBase(ABC):
    @abstractmethod
    async def create(self, target: Target) -> Target:
        """Persist a new target. Raise ValueError if target_id already exists."""

    @abstractmethod
    async def get(self, tenant_id: str, target_id: str) -> Target | None:
        """Look up one target, scoped to tenant_id."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: str) -> list[Target]:
        """Return every target belonging to one tenant."""

    @abstractmethod
    async def delete(self, tenant_id: str, target_id: str) -> None:
        """Remove one target. Raise NotFoundError if it doesn't exist for that tenant."""
