from __future__ import annotations

import pytest

from saas_job_api.jwt_tokens import InvalidTokenError, issue_token, verify_token


def test_issue_and_verify_round_trip() -> None:
    token = issue_token(secret="s3cret", subject="principal-1", role="platform_admin", ttl_seconds=3600)

    claims = verify_token(token, secret="s3cret")

    assert claims.subject == "principal-1"
    assert claims.role == "platform_admin"
    assert claims.expires_at > claims.issued_at


def test_verify_rejects_wrong_secret() -> None:
    token = issue_token(secret="s3cret", subject="principal-1", role="platform_admin", ttl_seconds=3600)

    with pytest.raises(InvalidTokenError):
        verify_token(token, secret="wrong-secret")


def test_verify_rejects_tampered_payload() -> None:
    token = issue_token(secret="s3cret", subject="principal-1", role="tenant_viewer", ttl_seconds=3600)
    header_b64, payload_b64, signature_b64 = token.split(".")

    tampered = f"{header_b64}.{payload_b64}extra.{signature_b64}"

    with pytest.raises(InvalidTokenError):
        verify_token(tampered, secret="s3cret")


def test_verify_rejects_expired_token() -> None:
    token = issue_token(secret="s3cret", subject="principal-1", role="platform_admin", ttl_seconds=-1)

    with pytest.raises(InvalidTokenError, match="expired"):
        verify_token(token, secret="s3cret")


def test_verify_rejects_malformed_token() -> None:
    with pytest.raises(InvalidTokenError):
        verify_token("not-a-jwt", secret="s3cret")


def test_issue_and_verify_round_trip_carries_tenant_id() -> None:
    token = issue_token(
        secret="s3cret", subject="principal-1", role="tenant_admin", ttl_seconds=3600, tenant_id="tenant-42"
    )

    claims = verify_token(token, secret="s3cret")

    assert claims.tenant_id == "tenant-42"


def test_tenant_id_defaults_to_none_for_an_unscoped_platform_admin_token() -> None:
    token = issue_token(secret="s3cret", subject="principal-1", role="platform_admin", ttl_seconds=3600)

    claims = verify_token(token, secret="s3cret")

    assert claims.tenant_id is None


def test_role_privilege_escalation_via_payload_swap_is_rejected() -> None:
    """A tenant_viewer token's payload segment can't be swapped for a
    platform_admin token's payload while keeping the platform_admin token's
    signature - the signature covers header+payload together, not just
    the header."""
    viewer_token = issue_token(secret="s3cret", subject="principal-1", role="tenant_viewer", ttl_seconds=3600)
    admin_token = issue_token(secret="s3cret", subject="principal-2", role="platform_admin", ttl_seconds=3600)

    header_b64, _, admin_signature_b64 = admin_token.split(".")
    _, viewer_payload_b64, _ = viewer_token.split(".")
    forged = f"{header_b64}.{viewer_payload_b64}.{admin_signature_b64}"

    with pytest.raises(InvalidTokenError):
        verify_token(forged, secret="s3cret")
