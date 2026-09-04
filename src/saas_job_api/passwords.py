"""PBKDF2-HMAC password hashing (stdlib only - no new dependency for this)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

_SCHEME = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_SCHEME}${_ITERATIONS}${base64.b64encode(salt).decode('ascii')}${base64.b64encode(derived).decode('ascii')}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations_str, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != _SCHEME:
        return False
    try:
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(expected, actual)
