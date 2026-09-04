from __future__ import annotations

from saas_job_api.passwords import hash_password, verify_password


def test_verify_accepts_the_correct_password() -> None:
    stored = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", stored) is True


def test_verify_rejects_the_wrong_password() -> None:
    stored = hash_password("correct horse battery staple")

    assert verify_password("wrong password", stored) is False


def test_hash_password_is_salted() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second  # different random salt each time
    assert verify_password("same-password", first) is True
    assert verify_password("same-password", second) is True


def test_verify_rejects_malformed_stored_hash() -> None:
    assert verify_password("anything", "not-a-real-hash") is False
