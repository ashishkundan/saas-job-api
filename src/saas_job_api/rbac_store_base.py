"""Abstract base class for admin principal (RBAC) storage."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .identity import AdminPrincipal


class RbacStoreBase(ABC):
    """Abstract interface for admin principal storage."""

    @abstractmethod
    async def create_principal(self, principal: AdminPrincipal) -> AdminPrincipal:
        """Persist a new admin principal. Raise ValueError if username exists."""

    @abstractmethod
    async def get_by_username(self, username: str) -> AdminPrincipal | None:
        """Look up an admin principal by username, for the login flow."""
