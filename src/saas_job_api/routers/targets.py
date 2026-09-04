"""Target CRUD (Phase 2.5), nested under a tenant. Create/delete require
platform_admin or tenant_admin; read (get/list) is open to any authenticated
admin principal including tenant_viewer. Every operation is scoped by
require_tenant_access against the tenant_id in the URL path."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import authenticated_admin_principal, require_any_role, require_tenant_access
from ..errors import ConflictError, NotFoundError
from ..identity import AdminRole
from ..jwt_tokens import TokenClaims
from ..models.tenancy import TargetCreateRequest, TargetResponse
from ..target_store_base import TargetStoreBase
from ..tenancy import Target, new_target_id
from ..time_provider import Clock

router = APIRouter(prefix="/admin/v1/tenants/{tenant_id}/targets", tags=["targets"])

_WRITE_ROLES = (AdminRole.PLATFORM_ADMIN, AdminRole.TENANT_ADMIN)


def get_target_store(request: Request) -> TargetStoreBase:
    return request.app.state.target_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def _to_response(target: Target) -> TargetResponse:
    return TargetResponse(
        targetId=target.target_id,
        tenantId=target.tenant_id,
        name=target.name,
        host=target.host,
        port=target.port,
        pluginRef=target.plugin_ref,
        pluginVersion=target.plugin_version,
        credentialRef=target.credential_ref,
        createdAt=target.created_at,
    )


@router.post("", response_model=TargetResponse)
async def create_target(
    tenant_id: str,
    body: TargetCreateRequest,
    store: TargetStoreBase = Depends(get_target_store),
    clock: Clock = Depends(get_clock),
    claims: TokenClaims = Depends(require_any_role(*_WRITE_ROLES)),
) -> TargetResponse:
    require_tenant_access(claims, tenant_id)
    target = Target(
        target_id=body.target_id or new_target_id(),
        tenant_id=tenant_id,
        name=body.name,
        host=body.host,
        port=body.port,
        plugin_ref=body.plugin_ref,
        plugin_version=body.plugin_version,
        credential_ref=body.credential_ref,
        created_at=clock.now(),
    )
    try:
        await store.create(target)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return _to_response(target)


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    tenant_id: str,
    store: TargetStoreBase = Depends(get_target_store),
    claims: TokenClaims = Depends(authenticated_admin_principal),
) -> list[TargetResponse]:
    require_tenant_access(claims, tenant_id)
    targets = await store.list_by_tenant(tenant_id)
    return [_to_response(t) for t in targets]


@router.get("/{target_id}", response_model=TargetResponse)
async def get_target(
    tenant_id: str,
    target_id: str,
    store: TargetStoreBase = Depends(get_target_store),
    claims: TokenClaims = Depends(authenticated_admin_principal),
) -> TargetResponse:
    require_tenant_access(claims, tenant_id)
    target = await store.get(tenant_id, target_id)
    if target is None:
        raise NotFoundError(f"target not found: {target_id}")
    return _to_response(target)


@router.delete("/{target_id}")
async def delete_target(
    tenant_id: str,
    target_id: str,
    store: TargetStoreBase = Depends(get_target_store),
    claims: TokenClaims = Depends(require_any_role(*_WRITE_ROLES)),
) -> dict[str, str]:
    require_tenant_access(claims, tenant_id)
    await store.delete(tenant_id, target_id)
    return {"status": "deleted", "targetId": target_id}
