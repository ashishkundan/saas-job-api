"""Integration tests for the Phase 1.1 registration + RBAC flow:
login -> issue enrollment token -> register a gateway (CSR -> cert) ->
look up registration status."""

from __future__ import annotations

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from conftest import make_test_settings
from saas_job_api.main import create_app

ADMIN_USERNAME = "platform-admin"
ADMIN_PASSWORD = "correct horse battery staple"


def _build_gateway_csr(gateway_id: str) -> tuple[Ed25519PrivateKey, str]:
    key = Ed25519PrivateKey.generate()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, gateway_id)]))
        .sign(key, algorithm=None)
    )
    return key, csr.public_bytes(Encoding.PEM).decode("ascii")


@pytest.fixture
async def client():
    app = create_app(
        settings=make_test_settings(
            bootstrap_admin_username=ADMIN_USERNAME,
            bootstrap_admin_password=ADMIN_PASSWORD,
        )
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _login(client: httpx.AsyncClient) -> str:
    resp = await client.post("/admin/v1/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["accessToken"]


async def test_login_rejects_wrong_password(client: httpx.AsyncClient) -> None:
    resp = await client.post("/admin/v1/login", json={"username": ADMIN_USERNAME, "password": "wrong"})
    assert resp.status_code == 401


async def test_login_rejects_unknown_username(client: httpx.AsyncClient) -> None:
    resp = await client.post("/admin/v1/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


async def test_enrollment_token_requires_authentication(client: httpx.AsyncClient) -> None:
    resp = await client.post("/admin/v1/enrollment-tokens")
    assert resp.status_code == 401


async def test_full_registration_flow_issues_a_certificate_that_chains_to_the_ca(client: httpx.AsyncClient) -> None:
    jwt = await _login(client)

    token_resp = await client.post("/admin/v1/enrollment-tokens", headers={"Authorization": f"Bearer {jwt}"})
    assert token_resp.status_code == 200, token_resp.text
    enrollment_token = token_resp.json()["token"]

    _, csr_pem = _build_gateway_csr("gw-integration-001")
    register_resp = await client.post(
        "/gateway/v1/register",
        json={"enrollmentToken": enrollment_token, "gatewayId": "gw-integration-001", "csrPem": csr_pem},
    )
    assert register_resp.status_code == 200, register_resp.text
    body = register_resp.json()

    issued = x509.load_pem_x509_certificate(body["certificatePem"].encode("ascii"))
    ca_cert = x509.load_pem_x509_certificate(body["caCertificatePem"].encode("ascii"))
    assert issued.issuer == ca_cert.subject
    ca_cert.public_key().verify(issued.signature, issued.tbs_certificate_bytes)  # raises if it doesn't chain

    status_resp = await client.get(
        "/gateway/v1/registration/gw-integration-001", headers={"Authorization": f"Bearer {jwt}"}
    )
    assert status_resp.status_code == 200, status_resp.text
    assert status_resp.json()["gatewayId"] == "gw-integration-001"


async def test_registration_status_for_unknown_gateway_is_404(client: httpx.AsyncClient) -> None:
    jwt = await _login(client)

    resp = await client.get("/gateway/v1/registration/gw-never-registered", headers={"Authorization": f"Bearer {jwt}"})

    assert resp.status_code == 404


async def test_enrollment_token_cannot_be_reused(client: httpx.AsyncClient) -> None:
    jwt = await _login(client)
    token_resp = await client.post("/admin/v1/enrollment-tokens", headers={"Authorization": f"Bearer {jwt}"})
    enrollment_token = token_resp.json()["token"]

    _, csr_pem_1 = _build_gateway_csr("gw-reuse-001")
    first = await client.post(
        "/gateway/v1/register",
        json={"enrollmentToken": enrollment_token, "gatewayId": "gw-reuse-001", "csrPem": csr_pem_1},
    )
    assert first.status_code == 200, first.text

    _, csr_pem_2 = _build_gateway_csr("gw-reuse-002")
    second = await client.post(
        "/gateway/v1/register",
        json={"enrollmentToken": enrollment_token, "gatewayId": "gw-reuse-002", "csrPem": csr_pem_2},
    )
    assert second.status_code == 401


async def test_register_rejects_unknown_enrollment_token(client: httpx.AsyncClient) -> None:
    _, csr_pem = _build_gateway_csr("gw-bad-token")

    resp = await client.post(
        "/gateway/v1/register",
        json={"enrollmentToken": "not-a-real-token", "gatewayId": "gw-bad-token", "csrPem": csr_pem},
    )

    assert resp.status_code == 401


async def test_register_rejects_malformed_csr(client: httpx.AsyncClient) -> None:
    jwt = await _login(client)
    token_resp = await client.post("/admin/v1/enrollment-tokens", headers={"Authorization": f"Bearer {jwt}"})
    enrollment_token = token_resp.json()["token"]

    resp = await client.post(
        "/gateway/v1/register",
        json={"enrollmentToken": enrollment_token, "gatewayId": "gw-bad-csr", "csrPem": "not a csr"},
    )

    assert resp.status_code == 400


async def test_gateway_registration_can_be_rotated_with_a_fresh_token(client: httpx.AsyncClient) -> None:
    """Re-registering the same gateway_id with a new enrollment token
    rotates its certificate rather than being rejected as a duplicate."""
    jwt = await _login(client)

    token_resp_1 = await client.post("/admin/v1/enrollment-tokens", headers={"Authorization": f"Bearer {jwt}"})
    _, csr_pem_1 = _build_gateway_csr("gw-rotate-001")
    first = await client.post(
        "/gateway/v1/register",
        json={
            "enrollmentToken": token_resp_1.json()["token"],
            "gatewayId": "gw-rotate-001",
            "csrPem": csr_pem_1,
        },
    )
    assert first.status_code == 200

    token_resp_2 = await client.post("/admin/v1/enrollment-tokens", headers={"Authorization": f"Bearer {jwt}"})
    _, csr_pem_2 = _build_gateway_csr("gw-rotate-001")
    second = await client.post(
        "/gateway/v1/register",
        json={
            "enrollmentToken": token_resp_2.json()["token"],
            "gatewayId": "gw-rotate-001",
            "csrPem": csr_pem_2,
        },
    )
    assert second.status_code == 200
    assert second.json()["certificatePem"] != first.json()["certificatePem"]
