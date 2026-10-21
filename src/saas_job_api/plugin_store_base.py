"""Plugin distribution storage: the signed plugin repository files the SaaS
serves to gateways, and per-tenant plugin entitlements.

The SaaS is *untrusted transport* for the repository (certificate-discovery-
engine docs/design/plugin-distribution-security.md): gateways verify every
file with TUF against their pinned root, so this store only keeps bytes. It
never parses or "fixes" them.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime

REPO_KINDS = ("metadata", "targets")
_METADATA_NAME = re.compile(r"^(timestamp|[0-9]{1,10}\.[a-z0-9][a-z0-9-]{0,62})\.json$")
_TARGET_PATH = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}/[0-9a-f]{64}\.[0-9A-Za-z][0-9A-Za-z.+-]{0,63}\.json$")
MAX_REPO_FILE_BYTES = 1024 * 1024
PLUGIN_REF = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Same rule as the gateway's signed release documents.
PLUGIN_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")


def valid_repo_path(kind: str, path: str) -> bool:
    """Only TUF consistent-snapshot names are stored or served - no
    traversal, no arbitrary files."""
    if kind == "metadata":
        return bool(_METADATA_NAME.match(path))
    if kind == "targets":
        return bool(_TARGET_PATH.match(path))
    return False


class PluginStoreBase(ABC):
    @abstractmethod
    async def put_repo_file(self, kind: str, path: str, content: bytes, *, now: datetime) -> None:
        """Store (or replace) one repository file."""

    @abstractmethod
    async def get_repo_file(self, kind: str, path: str) -> bytes | None:
        """Return one repository file, or None."""

    @abstractmethod
    async def grant(self, tenant_id: str, plugin_ref: str, *, now: datetime) -> bool:
        """Entitle a tenant to a plugin. Return False if it already was."""

    @abstractmethod
    async def revoke(self, tenant_id: str, plugin_ref: str) -> bool:
        """Remove an entitlement. Return False if there was none."""

    @abstractmethod
    async def list_plugins(self, tenant_id: str) -> list[str]:
        """Plugins a tenant is entitled to, sorted."""

    async def is_entitled(self, tenant_id: str, plugin_ref: str) -> bool:
        return plugin_ref in await self.list_plugins(tenant_id)

    # ---------------------------------------------- per-tenant version pin

    @abstractmethod
    async def pinned_versions(self, tenant_id: str) -> dict[str, str | None]:
        """Entitled plugins of a tenant -> the version pinned for that tenant
        (None = no pin; targets must then name a version themselves)."""

    @abstractmethod
    async def set_pinned_version(self, tenant_id: str, plugin_ref: str, version: str | None) -> str | None:
        """Pin (or with None, unpin) a tenant's version of an entitled plugin.
        Returns the previous pin. Raises KeyError if not entitled."""

    async def pinned_version(self, tenant_id: str, plugin_ref: str) -> str | None:
        return (await self.pinned_versions(tenant_id)).get(plugin_ref)

    @abstractmethod
    async def is_published(self, plugin_ref: str, version: str) -> bool:
        """True if a signed release document for plugin_ref/version was ever
        uploaded. (Revocation is in the signed metadata; gateways enforce it.)"""
