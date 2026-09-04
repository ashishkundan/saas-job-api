"""In-memory Target store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .errors import NotFoundError
from .tenancy import Target
from .target_store_base import TargetStoreBase


@dataclass
class MemoryTargetStore(TargetStoreBase):
    _targets: dict[str, Target] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def create(self, target: Target) -> Target:
        async with self._lock:
            if target.target_id in self._targets:
                raise ValueError(f"target_id already exists: {target.target_id}")
            self._targets[target.target_id] = target
            return target

    async def get(self, tenant_id: str, target_id: str) -> Target | None:
        async with self._lock:
            target = self._targets.get(target_id)
            return target if target is not None and target.tenant_id == tenant_id else None

    async def list_by_tenant(self, tenant_id: str) -> list[Target]:
        async with self._lock:
            return [t for t in self._targets.values() if t.tenant_id == tenant_id]

    async def delete(self, tenant_id: str, target_id: str) -> None:
        async with self._lock:
            target = self._targets.get(target_id)
            if target is None or target.tenant_id != tenant_id:
                raise NotFoundError(f"target not found: {target_id}")
            del self._targets[target_id]
