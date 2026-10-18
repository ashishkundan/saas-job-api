"""Plugin distribution endpoints.

* Gateways read the signed plugin repository (TUF metadata + release
  documents). The SaaS is untrusted transport: it serves stored bytes
  verbatim and gateways verify them against their pinned TUF root.
* The release pipeline uploads repository files (admin token).
* Platform admins grant/revoke per-tenant plugin entitlements; target and
  job creation (and the scheduler) only accept entitled plugins.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from ..audit import record_audit_event
from ..audit_store_base import AuditLogStoreBase
from ..auth import (
    authenticated_admin_principal,
    authenticated_gateway,
    require_admin_token,
    require_role,
    require_tenant_access,
)
from ..errors import BadRequestError, NotFoundError
from ..identity import AdminRole
from ..jwt_tokens import TokenClaims
from ..plugin_store_base import MAX_REPO_FILE_BYTES, PLUGIN_REF, PluginStoreBase, valid_repo_path
from ..tenant_store_base import TenantStoreBase
from ..time_provider import Clock


def get_plugin_store(request: Request) -> PluginStoreBase:
    return request.app.state.plugin_store


def get_tenant_store(request: Request) -> TenantStoreBase:
    return request.app.state.tenant_store


def get_audit_store(request: Request) -> AuditLogStoreBase:
    return request.app.state.audit_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


# ------------------------------------------------------------ gateway reads

gateway_router = APIRouter(prefix="/gateway/v1/plugin-repo", tags=["plugin-repo"])


async def _serve(kind: str, path: str, store: PluginStoreBase) -> Response:
    if not valid_repo_path(kind, path):
        raise NotFoundError("no such repository file")
    content = await store.get_repo_file(kind, path)
    if content is None:
        raise NotFoundError("no such repository file")
    # Metadata changes in place (timestamp.json); never let a proxy cache it.
    return Response(content=content, media_type="application/json", headers={"Cache-Control": "no-store"})


@gateway_router.get("/metadata/{path}")
async def get_metadata(path: str, store: PluginStoreBase = Depends(get_plugin_store),
                       gateway_id: str = Depends(authenticated_gateway)) -> Response:
    return await _serve("metadata", path, store)


@gateway_router.get("/targets/{path:path}")
async def get_target(path: str, store: PluginStoreBase = Depends(get_plugin_store),
                     gateway_id: str = Depends(authenticated_gateway)) -> Response:
    return await _serve("targets", path, store)


# ------------------------------------------------------------ pipeline upload

upload_router = APIRouter(prefix="/admin/plugin-repo", tags=["plugin-repo"], dependencies=[Depends(require_admin_token)])


@upload_router.put("/{kind}/{path:path}", status_code=204)
async def put_repo_file(kind: str, path: str, request: Request,
                        store: PluginStoreBase = Depends(get_plugin_store),
                        clock: Clock = Depends(get_clock)) -> Response:
    if not valid_repo_path(kind, path):
        raise BadRequestError(f"invalid repository path {kind}/{path}")
    content = await request.body()
    if not content or len(content) > MAX_REPO_FILE_BYTES:
        raise BadRequestError(f"repository files must be 1..{MAX_REPO_FILE_BYTES} bytes")
    await store.put_repo_file(kind, path, content, now=clock.now())
    return Response(status_code=204)


# ------------------------------------------------------- tenant entitlements

entitlement_router = APIRouter(prefix="/admin/v1/tenants/{tenant_id}/plugins", tags=["plugins"])


@entitlement_router.get("")
async def list_entitlements(tenant_id: str, store: PluginStoreBase = Depends(get_plugin_store),
                            claims: TokenClaims = Depends(authenticated_admin_principal)) -> dict:
    require_tenant_access(claims, tenant_id)
    return {"tenantId": tenant_id, "plugins": await store.list_plugins(tenant_id)}


@entitlement_router.put("/{plugin_ref}")
async def grant_entitlement(tenant_id: str, plugin_ref: str,
                            store: PluginStoreBase = Depends(get_plugin_store),
                            tenant_store: TenantStoreBase = Depends(get_tenant_store),
                            audit_store: AuditLogStoreBase = Depends(get_audit_store),
                            clock: Clock = Depends(get_clock),
                            claims: TokenClaims = Depends(require_role(AdminRole.PLATFORM_ADMIN))) -> dict:
    if not PLUGIN_REF.match(plugin_ref):
        raise BadRequestError(f"invalid plugin id {plugin_ref!r}")
    if await tenant_store.get(tenant_id) is None:
        raise NotFoundError(f"tenant not found: {tenant_id}")
    now = clock.now()
    if await store.grant(tenant_id, plugin_ref, now=now):
        await record_audit_event(audit_store, event_type="PLUGIN_ENTITLEMENT_GRANTED", actor=claims.subject,
                                 tenant_id=tenant_id, resource_type="plugin", resource_id=plugin_ref, now=now)
    return {"tenantId": tenant_id, "plugins": await store.list_plugins(tenant_id)}


@entitlement_router.delete("/{plugin_ref}")
async def revoke_entitlement(tenant_id: str, plugin_ref: str,
                             store: PluginStoreBase = Depends(get_plugin_store),
                             audit_store: AuditLogStoreBase = Depends(get_audit_store),
                             clock: Clock = Depends(get_clock),
                             claims: TokenClaims = Depends(require_role(AdminRole.PLATFORM_ADMIN))) -> dict:
    if not await store.revoke(tenant_id, plugin_ref):
        raise NotFoundError(f"tenant {tenant_id} is not entitled to {plugin_ref}")
    await record_audit_event(audit_store, event_type="PLUGIN_ENTITLEMENT_REVOKED", actor=claims.subject,
                             tenant_id=tenant_id, resource_type="plugin", resource_id=plugin_ref, now=clock.now())
    return {"tenantId": tenant_id, "plugins": await store.list_plugins(tenant_id)}
