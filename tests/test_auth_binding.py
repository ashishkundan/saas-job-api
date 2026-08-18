from __future__ import annotations


async def test_malformed_authorization_header_is_401(client):
    resp = await client.post(
        "/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers={"Authorization": "test-gateway-token"}
    )
    assert resp.status_code == 401


async def test_admin_route_requires_admin_token(client):
    resp = await client.get("/admin/jobs")
    assert resp.status_code == 401


async def test_admin_route_rejects_wrong_admin_token(client):
    resp = await client.get("/admin/jobs", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


async def test_admin_token_does_not_authenticate_gateway_routes(client, admin_headers):
    resp = await client.post(
        "/gateway/v1/jobs/poll",
        json={"maxJobs": 20},
        headers={"Authorization": f"Bearer {admin_headers['X-Admin-Token']}"},
    )
    assert resp.status_code == 401
