"""Minimal HS256 JWT issuance/verification for the admin RBAC login flow.

Hand-rolled with stdlib hmac/hashlib/base64/json rather than a new
third-party dependency - HS256 is simple enough to implement correctly in
~50 lines, and this repo already takes on one new crypto dependency
(cryptography, for gateway mTLS) without needing a second, JWT-specific one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


class InvalidTokenError(ValueError):
    """Token is malformed, has an invalid signature, or has expired."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


@dataclass(slots=True, frozen=True)
class TokenClaims:
    subject: str
    role: str
    issued_at: int
    expires_at: int


def issue_token(*, secret: str, subject: str, role: str, ttl_seconds: float) -> str:
    now = int(time.time())
    header_b64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(
        json.dumps({"sub": subject, "role": role, "iat": now, "exp": now + int(ttl_seconds)}, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def verify_token(token: str, *, secret: str) -> TokenClaims:
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError("malformed token")
    header_b64, payload_b64, signature_b64 = parts

    signing_input = f"{header_b64}.{payload_b64}"
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    try:
        actual_signature = _b64url_decode(signature_b64)
    except Exception as exc:
        raise InvalidTokenError("malformed signature") from exc
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise InvalidTokenError("signature mismatch")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise InvalidTokenError("malformed payload") from exc

    if not isinstance(payload, dict):
        raise InvalidTokenError("malformed payload")

    now = int(time.time())
    if payload.get("exp", 0) < now:
        raise InvalidTokenError("token expired")

    try:
        return TokenClaims(
            subject=payload["sub"],
            role=payload["role"],
            issued_at=payload["iat"],
            expires_at=payload["exp"],
        )
    except KeyError as exc:
        raise InvalidTokenError(f"missing claim: {exc}") from exc
