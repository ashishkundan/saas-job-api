"""RBAC login - POST /admin/v1/login, issuing the short-lived JWT that
authenticated_admin_principal/require_role verify (open question #9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..audit import record_audit_event
from ..audit_store_base import AuditLogStoreBase
from ..auth import get_settings
from ..config import Settings
from ..errors import UnauthorizedError
from ..jwt_tokens import issue_token
from ..models.registration import AdminLoginRequest, AdminLoginResponse
from ..passwords import verify_password
from ..rbac_store_base import RbacStoreBase
from ..time_provider import Clock

router = APIRouter(prefix="/admin/v1", tags=["admin-auth"])


def get_rbac_store(request: Request) -> RbacStoreBase:
    return request.app.state.rbac_store


def get_audit_store(request: Request) -> AuditLogStoreBase:
    return request.app.state.audit_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


@router.post("/login", response_model=AdminLoginResponse)
async def login(
    body: AdminLoginRequest,
    store: RbacStoreBase = Depends(get_rbac_store),
    audit_store: AuditLogStoreBase = Depends(get_audit_store),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> AdminLoginResponse:
    principal = await store.get_by_username(body.username)
    if principal is None or not verify_password(body.password, principal.password_hash):
        # Logs the attempted username, never the password - useful for
        # brute-force/credential-stuffing detection either way (unknown
        # username or wrong password produce the identical audit entry,
        # matching UnauthorizedError's own "don't disclose which" stance).
        await record_audit_event(
            audit_store, event_type="ADMIN_LOGIN_FAILED", actor=body.username, now=clock.now()
        )
        raise UnauthorizedError()

    await record_audit_event(
        audit_store,
        event_type="ADMIN_LOGIN_SUCCEEDED",
        actor=principal.username,
        tenant_id=principal.tenant_id,
        now=clock.now(),
    )

    token = issue_token(
        secret=settings.jwt_secret,
        subject=principal.principal_id,
        role=principal.role.value,
        ttl_seconds=settings.jwt_ttl_seconds,
        tenant_id=principal.tenant_id,
    )
    return AdminLoginResponse(
        accessToken=token,
        expiresIn=int(settings.jwt_ttl_seconds),
        role=principal.role.value,
        tenantId=principal.tenant_id,
    )
