"""Gateway registration (mTLS enrollment) - POST /admin/v1/enrollment-tokens,
POST /gateway/v1/register, GET /gateway/v1/registration/{gatewayId}.

Open question #2 (locked): registration issues a short-lived mTLS client
certificate, not a bearer token. The plaintext enrollment token is shown
exactly once, at issuance - only its hash is ever persisted.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509 import load_pem_x509_csr
from fastapi import APIRouter, Depends, Request

from ..audit import record_audit_event
from ..audit_store_base import AuditLogStoreBase
from ..auth import authenticated_admin_principal, get_settings, require_role
from ..certs import CertificateAuthority, InvalidCsrError
from ..config import Settings
from ..errors import BadRequestError, NotFoundError, UnauthorizedError
from ..identity import AdminRole, EnrollmentToken, GatewayIdentity, GatewayIdentityTenantMismatch
from ..models.registration import (
    EnrollmentTokenRequest,
    EnrollmentTokenResponse,
    GatewayRegisterRequest,
    GatewayRegisterResponse,
    GatewayRegistrationStatusResponse,
)
from ..registration_store_base import RegistrationStoreBase
from ..tenant_store_base import TenantStoreBase
from ..time_provider import Clock

admin_router = APIRouter(prefix="/admin/v1", tags=["registration-admin"])
gateway_router = APIRouter(prefix="/gateway/v1", tags=["registration-gateway"])


def get_audit_store(request: Request) -> AuditLogStoreBase:
    return request.app.state.audit_store


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_registration_store(request: Request) -> RegistrationStoreBase:
    return request.app.state.registration_store


def get_tenant_store(request: Request) -> TenantStoreBase:
    return request.app.state.tenant_store


def get_ca(request: Request) -> CertificateAuthority:
    return request.app.state.ca


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


@admin_router.post("/enrollment-tokens", response_model=EnrollmentTokenResponse)
async def issue_enrollment_token(
    request: Request,
    body: EnrollmentTokenRequest | None = None,
    store: RegistrationStoreBase = Depends(get_registration_store),
    tenant_store: TenantStoreBase = Depends(get_tenant_store),
    audit_store: AuditLogStoreBase = Depends(get_audit_store),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
    principal=Depends(require_role(AdminRole.PLATFORM_ADMIN)),
) -> EnrollmentTokenResponse:
    tenant_id = body.tenant_id if body is not None else None
    if tenant_id is not None and await tenant_store.get(tenant_id) is None:
        raise NotFoundError("Tenant not found")
    plaintext = secrets.token_urlsafe(32)
    now = clock.now()
    token = EnrollmentToken(
        token_id=str(uuid.uuid4()),
        token_hash=_hash_token(plaintext),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.enrollment_token_ttl_seconds),
        issued_by=principal.subject,
        tenant_id=tenant_id,
    )
    await store.create_enrollment_token(token)
    await record_audit_event(
        audit_store,
        event_type="ENROLLMENT_TOKEN_ISSUED",
        actor=principal.subject,
        resource_type="enrollment_token",
        resource_id=token.token_id,
        now=now,
        tenant_id=tenant_id,
    )
    return EnrollmentTokenResponse(token=plaintext, expiresAt=token.expires_at)


@gateway_router.post("/register", response_model=GatewayRegisterResponse)
async def register_gateway(
    body: GatewayRegisterRequest,
    store: RegistrationStoreBase = Depends(get_registration_store),
    audit_store: AuditLogStoreBase = Depends(get_audit_store),
    ca: CertificateAuthority = Depends(get_ca),
    clock: Clock = Depends(get_clock),
) -> GatewayRegisterResponse:
    token = await store.get_enrollment_token_by_hash(_hash_token(body.enrollment_token))
    now = clock.now()
    if token is None or token.is_used or token.is_expired(now):
        # Same response whether the token is unknown, expired, or already
        # used - doesn't leak which, and matches the existing UnauthorizedError
        # convention (no separate state-disclosing error code).
        raise UnauthorizedError()

    try:
        certificate_pem, serial, not_after = ca.sign_gateway_csr(
            body.csr_pem.encode("utf-8"), gateway_id=body.gateway_id
        )
    except InvalidCsrError as exc:
        raise BadRequestError(str(exc)) from exc

    csr = load_pem_x509_csr(body.csr_pem.encode("utf-8"))
    try:
        public_key_bytes = csr.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    except (ValueError, TypeError) as exc:
        # Raw encoding only applies to Ed25519/X25519/Ed448/X448 keys - the
        # Gateway VM plan standardizes on Ed25519 throughout, so any other
        # key type is rejected rather than silently mis-fingerprinted.
        raise BadRequestError("gateway public key must be Ed25519") from exc
    fingerprint = hashlib.sha256(public_key_bytes).hexdigest()

    existing = await store.get_gateway_identity(body.gateway_id)
    if existing is not None and existing.tenant_id is not None and existing.tenant_id != token.tenant_id:
        raise UnauthorizedError()
    identity = GatewayIdentity(
        gateway_id=body.gateway_id,
        public_key_fingerprint=fingerprint,
        certificate_pem=certificate_pem.decode("ascii"),
        certificate_serial=serial,
        certificate_not_after=not_after,
        registered_at=existing.registered_at if existing is not None else now,
        last_rotated_at=now,
        tenant_id=(existing.tenant_id if existing is not None else None) or token.tenant_id,
    )
    try:
        await store.upsert_gateway_identity(identity)
    except GatewayIdentityTenantMismatch as exc:
        raise UnauthorizedError() from exc
    await store.mark_enrollment_token_used(token.token_id, used_at=now, gateway_id=body.gateway_id)
    await record_audit_event(
        audit_store,
        event_type="GATEWAY_REGISTERED",
        actor=body.gateway_id,
        resource_type="gateway",
        resource_id=body.gateway_id,
        now=now,
    )

    return GatewayRegisterResponse(
        gatewayId=body.gateway_id,
        certificatePem=identity.certificate_pem,
        caCertificatePem=ca.ca_certificate_pem.decode("ascii"),
        notAfter=not_after,
    )


@gateway_router.get("/registration/{gateway_id}", response_model=GatewayRegistrationStatusResponse)
async def get_registration_status(
    gateway_id: str,
    store: RegistrationStoreBase = Depends(get_registration_store),
    principal=Depends(authenticated_admin_principal),
) -> GatewayRegistrationStatusResponse:
    del principal  # any authenticated admin principal may look up status
    identity = await store.get_gateway_identity(gateway_id)
    if identity is None:
        raise NotFoundError(f"gateway '{gateway_id}' is not registered")
    return GatewayRegistrationStatusResponse(
        gatewayId=identity.gateway_id,
        certificateSerial=identity.certificate_serial,
        certificateNotAfter=identity.certificate_not_after,
        registeredAt=identity.registered_at,
        lastRotatedAt=identity.last_rotated_at,
    )
