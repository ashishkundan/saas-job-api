"""Plugin distribution endpoints.

* Gateways read the signed plugin repository (TUF metadata + release
  documents). The SaaS is untrusted transport: it serves stored bytes
  verbatim and gateways verify them against their pinned TUF root.
* The release pipeline uploads repository files (admin token).
* Platform admins grant/revoke per-tenant plugin entitlements; target and
  job creation (and the scheduler) only accept entitled plugins.
* An entitlement can carry the tenant's pinned plugin version: targets
  without their own pluginVersion run it, so a customer is upgraded,
  held back or rolled back with one call.
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
from ..errors import BadRequestError, ConflictError, NotFoundError
from ..identity import AdminRole
from ..jwt_tokens import TokenClaims
from ..models.tenancy import PluginEntitlementRequest
from ..plugin_store_base import MAX_REPO_FILE_BYTES, PLUGIN_REF, PluginStoreBase, valid_repo_path
from ..target_store_base import TargetStoreBase
from ..tenant_store_base import TenantStoreBase
from ..time_provider import Clock


def get_plugin_store(request: Request) -> PluginStoreBase:
    return request.app.state.plugin_store


def get_tenant_store(request: Request) -> TenantStoreBase:
    return request.app.state.tenant_store


def get_target_store(request: Request) -> TargetStoreBase:
    return request.app.state.target_store


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
    return await _entitlements(store, tenant_id)


async def _entitlements(store: PluginStoreBase, tenant_id: str) -> dict:
    pins = await store.pinned_versions(tenant_id)
    return {"tenantId": tenant_id, "plugins": sorted(pins), "pinnedVersions": pins}


@entitlement_router.put("/{plugin_ref}")
async def grant_entitlement(tenant_id: str, plugin_ref: str,
                            body: PluginEntitlementRequest | None = None,
                            store: PluginStoreBase = Depends(get_plugin_store),
                            tenant_store: TenantStoreBase = Depends(get_tenant_store),
                            target_store: TargetStoreBase = Depends(get_target_store),
                            audit_store: AuditLogStoreBase = Depends(get_audit_store),
                            clock: Clock = Depends(get_clock),
                            claims: TokenClaims = Depends(require_role(AdminRole.PLATFORM_ADMIN))) -> dict:
    """Grant (idempotent), and with a body, pin the tenant's version."""
    if not PLUGIN_REF.match(plugin_ref):
        raise BadRequestError(f"invalid plugin id {plugin_ref!r}")
    if await tenant_store.get(tenant_id) is None:
        raise NotFoundError(f"tenant not found: {tenant_id}")
    pin_requested = body is not None and "version" in body.model_fields_set
    if body is not None and body.reset_target_overrides and not (pin_requested and body.version):
        raise BadRequestError("resetTargetOverrides needs a version to move the targets to")
    if pin_requested and body.version is not None and not await store.is_published(plugin_ref, body.version):
        raise BadRequestError(f"{plugin_ref} {body.version} has not been published")
    if pin_requested and body.version is None:
        followers = [t.target_id for t in await target_store.list_by_tenant(tenant_id)
                     if t.plugin_ref == plugin_ref and t.plugin_version is None]
        if followers:
            raise ConflictError(
                f"targets {followers} follow the pinned version of {plugin_ref}; "
                "give them their own pluginVersion or pin another version first"
            )

    now = clock.now()
    if await store.grant(tenant_id, plugin_ref, now=now):
        await record_audit_event(audit_store, event_type="PLUGIN_ENTITLEMENT_GRANTED", actor=claims.subject,
                                 tenant_id=tenant_id, resource_type="plugin", resource_id=plugin_ref, now=now)
    if pin_requested:
        previous = await store.set_pinned_version(tenant_id, plugin_ref, body.version)
        moved = 0
        if body.reset_target_overrides:
            moved = await target_store.clear_version_overrides(tenant_id, plugin_ref)
        if previous != body.version or moved:
            await record_audit_event(
                audit_store, event_type="PLUGIN_VERSION_PINNED", actor=claims.subject, tenant_id=tenant_id,
                resource_type="plugin", resource_id=plugin_ref, now=now,
                detail={"previousVersion": previous, "version": body.version, "targetOverridesCleared": moved},
            )
    return await _entitlements(store, tenant_id)


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
    return await _entitlements(store, tenant_id)
