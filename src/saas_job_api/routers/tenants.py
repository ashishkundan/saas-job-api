"""Tenant CRUD (Phase 2.5). Creating/listing/deleting tenants is a
platform-level operation - platform_admin only. Reading a single tenant is
open to any authenticated admin principal, scoped by require_tenant_access
(platform_admin: any tenant; tenant_admin/tenant_viewer: only their own)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import require_role, require_tenant_access, authenticated_admin_principal
from ..errors import ConflictError, NotFoundError
from ..identity import AdminRole
from ..jwt_tokens import TokenClaims
from ..models.tenancy import TenantCreateRequest, TenantResponse
from ..tenancy import Tenant, new_tenant_id
from ..tenant_store_base import TenantStoreBase
from ..time_provider import Clock

router = APIRouter(prefix="/admin/v1/tenants", tags=["tenants"])


def get_tenant_store(request: Request) -> TenantStoreBase:
    return request.app.state.tenant_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def _to_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse(
        tenantId=tenant.tenant_id, name=tenant.name, createdAt=tenant.created_at, isActive=tenant.is_active
    )


@router.post("", response_model=TenantResponse)
async def create_tenant(
    body: TenantCreateRequest,
    store: TenantStoreBase = Depends(get_tenant_store),
    clock: Clock = Depends(get_clock),
    _claims: TokenClaims = Depends(require_role(AdminRole.PLATFORM_ADMIN)),
) -> TenantResponse:
    tenant = Tenant(tenant_id=body.tenant_id or new_tenant_id(), name=body.name, created_at=clock.now())
    try:
        await store.create(tenant)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return _to_response(tenant)


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    store: TenantStoreBase = Depends(get_tenant_store),
    _claims: TokenClaims = Depends(require_role(AdminRole.PLATFORM_ADMIN)),
) -> list[TenantResponse]:
    tenants = await store.list_all()
    return [_to_response(t) for t in tenants]


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    store: TenantStoreBase = Depends(get_tenant_store),
    claims: TokenClaims = Depends(authenticated_admin_principal),
) -> TenantResponse:
    require_tenant_access(claims, tenant_id)
    tenant = await store.get(tenant_id)
    if tenant is None:
        raise NotFoundError(f"tenant not found: {tenant_id}")
    return _to_response(tenant)


@router.delete("/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    store: TenantStoreBase = Depends(get_tenant_store),
    _claims: TokenClaims = Depends(require_role(AdminRole.PLATFORM_ADMIN)),
) -> dict[str, str]:
    await store.delete(tenant_id)
    return {"status": "deleted", "tenantId": tenant_id}
