"""Authenticated Gateway config reads and tenant-scoped admin changes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..audit import record_audit_event
from ..audit_store_base import AuditLogStoreBase
from ..auth import (
    authenticated_admin_principal,
    authenticated_gateway,
    get_settings,
    require_any_role,
    require_tenant_access,
)
from ..config import Settings
from ..errors import NotFoundError
from ..gateway_operational_config import (
    SCHEMA_VERSION,
    GatewayConfigTenantMismatch,
    GatewayOperationalConfig,
)
from ..gateway_operational_config_store_base import GatewayOperationalConfigStoreBase
from ..identity import AdminRole
from ..jwt_tokens import TokenClaims
from ..models.gateway_config import GatewayOperationalConfigResponse, GatewayOperationalConfigUpdate
from ..tenant_store_base import TenantStoreBase
from ..time_provider import Clock

router = APIRouter(tags=["gateway-config"])
_WRITE_ROLES = (AdminRole.PLATFORM_ADMIN, AdminRole.TENANT_ADMIN)


def get_config_store(request: Request) -> GatewayOperationalConfigStoreBase:
    return request.app.state.gateway_operational_config_store


def get_tenant_store(request: Request) -> TenantStoreBase:
    return request.app.state.tenant_store


def get_audit_store(request: Request) -> AuditLogStoreBase:
    return request.app.state.audit_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def _response(
    config: GatewayOperationalConfig | None,
    *,
    default_poll_interval_ms: int,
    default_heartbeat_interval_ms: int,
) -> GatewayOperationalConfigResponse:
    if config is None:
        return GatewayOperationalConfigResponse(
            schemaVersion=SCHEMA_VERSION,
            configVersion=0,
            pollIntervalMs=default_poll_interval_ms,
            heartbeatIntervalMs=default_heartbeat_interval_ms,
            acceptNewJobs=True,
        )
    return GatewayOperationalConfigResponse(
        schemaVersion=SCHEMA_VERSION,
        configVersion=config.config_version,
        pollIntervalMs=config.poll_interval_ms,
        heartbeatIntervalMs=config.heartbeat_interval_ms,
        acceptNewJobs=config.accept_new_jobs,
        updatedAt=config.updated_at,
    )


@router.get("/gateway/v1/config", response_model=GatewayOperationalConfigResponse)
async def get_gateway_config(
    config_store: GatewayOperationalConfigStoreBase = Depends(get_config_store),
    settings: Settings = Depends(get_settings),
    gateway_id: str = Depends(authenticated_gateway),
) -> GatewayOperationalConfigResponse:
    config = await config_store.get(gateway_id)
    return _response(
        config,
        default_poll_interval_ms=settings.default_poll_after_ms,
        default_heartbeat_interval_ms=settings.default_gateway_heartbeat_interval_ms,
    )


@router.get(
    "/admin/v1/tenants/{tenant_id}/gateways/{gateway_id}/config",
    response_model=GatewayOperationalConfigResponse,
)
async def get_admin_gateway_config(
    tenant_id: str,
    gateway_id: str,
    config_store: GatewayOperationalConfigStoreBase = Depends(get_config_store),
    claims: TokenClaims = Depends(authenticated_admin_principal),
) -> GatewayOperationalConfigResponse:
    require_tenant_access(claims, tenant_id)
    config = await config_store.get(gateway_id)
    if config is None or config.tenant_id != tenant_id:
        raise NotFoundError("Gateway configuration not found")
    return _response(
        config,
        default_poll_interval_ms=config.poll_interval_ms,
        default_heartbeat_interval_ms=config.heartbeat_interval_ms,
    )


@router.put(
    "/admin/v1/tenants/{tenant_id}/gateways/{gateway_id}/config",
    response_model=GatewayOperationalConfigResponse,
)
async def update_admin_gateway_config(
    tenant_id: str,
    gateway_id: str,
    body: GatewayOperationalConfigUpdate,
    config_store: GatewayOperationalConfigStoreBase = Depends(get_config_store),
    tenant_store: TenantStoreBase = Depends(get_tenant_store),
    audit_store: AuditLogStoreBase = Depends(get_audit_store),
    clock: Clock = Depends(get_clock),
    claims: TokenClaims = Depends(require_any_role(*_WRITE_ROLES)),
) -> GatewayOperationalConfigResponse:
    require_tenant_access(claims, tenant_id)
    if await tenant_store.get(tenant_id) is None:
        raise NotFoundError("Tenant not found")

    previous = await config_store.get(gateway_id)
    if previous is None and claims.role != AdminRole.PLATFORM_ADMIN.value:
        raise NotFoundError("Gateway configuration not found")
    if previous is not None and previous.tenant_id != tenant_id:
        raise NotFoundError("Gateway configuration not found")

    same_values = previous is not None and (
        previous.poll_interval_ms == body.poll_interval_ms
        and previous.heartbeat_interval_ms == body.heartbeat_interval_ms
        and previous.accept_new_jobs == body.accept_new_jobs
    )
    if same_values:
        return _response(
            previous,
            default_poll_interval_ms=previous.poll_interval_ms,
            default_heartbeat_interval_ms=previous.heartbeat_interval_ms,
        )

    try:
        updated = await config_store.save(
            gateway_id=gateway_id,
            tenant_id=tenant_id,
            poll_interval_ms=body.poll_interval_ms,
            heartbeat_interval_ms=body.heartbeat_interval_ms,
            accept_new_jobs=body.accept_new_jobs,
            updated_at=clock.now(),
        )
    except GatewayConfigTenantMismatch as exc:
        raise NotFoundError("Gateway configuration not found") from exc

    await record_audit_event(
        audit_store,
        event_type="GATEWAY_OPERATIONAL_CONFIG_UPDATED",
        actor=claims.subject,
        tenant_id=tenant_id,
        resource_type="gateway_config",
        resource_id=gateway_id,
        now=updated.updated_at,
        detail={
            "previous": (
                {
                    "pollIntervalMs": previous.poll_interval_ms,
                    "heartbeatIntervalMs": previous.heartbeat_interval_ms,
                    "acceptNewJobs": previous.accept_new_jobs,
                    "configVersion": previous.config_version,
                }
                if previous is not None
                else None
            ),
            "current": {
                "pollIntervalMs": updated.poll_interval_ms,
                "heartbeatIntervalMs": updated.heartbeat_interval_ms,
                "acceptNewJobs": updated.accept_new_jobs,
                "configVersion": updated.config_version,
            },
        },
    )
    return _response(
        updated,
        default_poll_interval_ms=updated.poll_interval_ms,
        default_heartbeat_interval_ms=updated.heartbeat_interval_ms,
    )
