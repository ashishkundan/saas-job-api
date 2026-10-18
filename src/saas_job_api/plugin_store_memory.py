"""In-memory plugin distribution store for development and testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from .plugin_store_base import PluginStoreBase


@dataclass
class MemoryPluginStore(PluginStoreBase):
    _files: dict[tuple[str, str], bytes] = field(default_factory=dict)
    _entitlements: set[tuple[str, str]] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def put_repo_file(self, kind: str, path: str, content: bytes, *, now: datetime) -> None:
        async with self._lock:
            self._files[(kind, path)] = bytes(content)

    async def get_repo_file(self, kind: str, path: str) -> bytes | None:
        async with self._lock:
            return self._files.get((kind, path))

    async def grant(self, tenant_id: str, plugin_ref: str, *, now: datetime) -> bool:
        async with self._lock:
            if (tenant_id, plugin_ref) in self._entitlements:
                return False
            self._entitlements.add((tenant_id, plugin_ref))
            return True

    async def revoke(self, tenant_id: str, plugin_ref: str) -> bool:
        async with self._lock:
            if (tenant_id, plugin_ref) not in self._entitlements:
                return False
            self._entitlements.discard((tenant_id, plugin_ref))
            return True

    async def list_plugins(self, tenant_id: str) -> list[str]:
        async with self._lock:
            return sorted(p for t, p in self._entitlements if t == tenant_id)
