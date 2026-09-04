"""Gateway bearer-token binding and admin-token checks.

The authoritative gateway identity always comes from the bearer token, never
from the request body -- a body-supplied gatewayId is only used to cross-check
against the token-bound identity.

Settings are read from request.app.state.settings (set in main.create_app),
not a module-level singleton, so each test app instance can use its own
token map without leaking state across tests.
"""

from __future__ import annotations

from fastapi import Depends, Header, Request

from .config import Settings, settings as default_settings
from .errors import ForbiddenError, UnauthorizedError
from .identity import AdminRole
from .jwt_tokens import InvalidTokenError, TokenClaims, verify_token


def get_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", default_settings)


async def authenticated_gateway(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError()
    token = authorization.removeprefix("Bearer ").strip()
    gateway_id = get_settings(request).gateway_tokens.get(token)
    if gateway_id is None:
        raise UnauthorizedError()
    return gateway_id


def bind_gateway_id(body_gateway_id: str | None, token_gateway_id: str) -> str:
    if body_gateway_id is not None and body_gateway_id != token_gateway_id:
        raise ForbiddenError()
    return token_gateway_id


async def require_admin_token(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    if x_admin_token != get_settings(request).admin_token:
        raise UnauthorizedError()


async def authenticated_admin_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> TokenClaims:
    """Verify a short-lived JWT issued by POST /admin/v1/login (open question
    #9: JWT over a static token map, since this guards the tenant/platform
    admin trust boundary). Kept entirely separate from require_admin_token,
    which continues gating the pre-existing dev/test /admin/jobs routes
    behind a flag for one release before deletion in Phase 4."""

    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError()
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_token(token, secret=get_settings(request).jwt_secret)
    except InvalidTokenError:
        raise UnauthorizedError() from None


def require_role(role: AdminRole):
    """Exact-role dependency factory (no hierarchy yet - platform_admin does
    not implicitly satisfy a tenant_admin/tenant_viewer requirement). There is
    only one gated endpoint as of Phase 1.1 (enrollment-token issuance,
    platform_admin-only); revisit hierarchy once Phase 2.5's tenant-scoped
    endpoints need it."""

    async def _check(claims: TokenClaims = Depends(authenticated_admin_principal)) -> TokenClaims:
        if claims.role != role.value:
            raise ForbiddenError()
        return claims

    return _check
