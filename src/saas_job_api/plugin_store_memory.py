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
    _pins: dict[tuple[str, str], str] = field(default_factory=dict)
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
            self._pins.pop((tenant_id, plugin_ref), None)
            return True

    async def list_plugins(self, tenant_id: str) -> list[str]:
        async with self._lock:
            return sorted(p for t, p in self._entitlements if t == tenant_id)

    async def pinned_versions(self, tenant_id: str) -> dict[str, str | None]:
        async with self._lock:
            return {p: self._pins.get((t, p)) for t, p in sorted(self._entitlements) if t == tenant_id}

    async def set_pinned_version(self, tenant_id: str, plugin_ref: str, version: str | None) -> str | None:
        async with self._lock:
            if (tenant_id, plugin_ref) not in self._entitlements:
                raise KeyError(plugin_ref)
            previous = self._pins.get((tenant_id, plugin_ref))
            if version is None:
                self._pins.pop((tenant_id, plugin_ref), None)
            else:
                self._pins[(tenant_id, plugin_ref)] = version
            return previous

    async def is_published(self, plugin_ref: str, version: str) -> bool:
        async with self._lock:
            return any(kind == "targets" and _is_release_path(path, plugin_ref, version) for kind, path in self._files)


def _is_release_path(path: str, plugin_ref: str, version: str) -> bool:
    plugin, _, name = path.partition("/")
    return plugin == plugin_ref and name.endswith(f".{version}.json") and len(name) == 64 + len(version) + 6
