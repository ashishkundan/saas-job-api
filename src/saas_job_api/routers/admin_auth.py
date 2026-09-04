"""RBAC login - POST /admin/v1/login, issuing the short-lived JWT that
authenticated_admin_principal/require_role verify (open question #9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import get_settings
from ..config import Settings
from ..errors import UnauthorizedError
from ..jwt_tokens import issue_token
from ..models.registration import AdminLoginRequest, AdminLoginResponse
from ..passwords import verify_password
from ..rbac_store_base import RbacStoreBase

router = APIRouter(prefix="/admin/v1", tags=["admin-auth"])


def get_rbac_store(request: Request) -> RbacStoreBase:
    return request.app.state.rbac_store


@router.post("/login", response_model=AdminLoginResponse)
async def login(
    body: AdminLoginRequest,
    store: RbacStoreBase = Depends(get_rbac_store),
    settings: Settings = Depends(get_settings),
) -> AdminLoginResponse:
    principal = await store.get_by_username(body.username)
    if principal is None or not verify_password(body.password, principal.password_hash):
        raise UnauthorizedError()

    token = issue_token(
        secret=settings.jwt_secret,
        subject=principal.principal_id,
        role=principal.role.value,
        ttl_seconds=settings.jwt_ttl_seconds,
    )
    return AdminLoginResponse(
        accessToken=token,
        expiresIn=int(settings.jwt_ttl_seconds),
        role=principal.role.value,
    )
