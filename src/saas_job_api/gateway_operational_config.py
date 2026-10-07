"""Non-secret, per-Gateway operational settings exposed by the Gateway API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SCHEMA_VERSION = 1
DEFAULT_HEARTBEAT_INTERVAL_MS = 60_000
MIN_POLL_INTERVAL_MS = 500
MAX_POLL_INTERVAL_MS = 300_000
MIN_HEARTBEAT_INTERVAL_MS = 1_000
# Keep Gateway heartbeats frequent enough for the SaaS 300s unreachable
# threshold and the scheduler's orphan-reissue decision.
MAX_HEARTBEAT_INTERVAL_MS = 60_000


@dataclass(slots=True, frozen=True)
class GatewayOperationalConfig:
    gateway_id: str
    tenant_id: str
    poll_interval_ms: int
    heartbeat_interval_ms: int
    accept_new_jobs: bool
    config_version: int
    updated_at: datetime


class GatewayConfigTenantMismatch(ValueError):
    """Raised when an existing Gateway configuration is assigned elsewhere."""

    def __init__(self, gateway_id: str) -> None:
        super().__init__(f"Gateway {gateway_id!r} is already assigned to another tenant")
