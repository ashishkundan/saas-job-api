"""Malformed requests: 400 MALFORMED_REQUEST with type/loc/msg only."""

from __future__ import annotations


async def test_validation_error_does_not_echo_request_input(client) -> None:
    resp = await client.post("/admin/v1/login", json={"username": "someone", "password": ["s3cret-value"]})

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "MALFORMED_REQUEST"
    assert "s3cret-value" not in resp.text
    assert all(set(e) == {"type", "loc", "msg"} for e in body["detail"])
