"""Opt-in verification that the parent repo's real RegistrationAgent can
register a gateway against a live instance of this server end-to-end -
Ed25519 keypair generation, CSR building, and the resulting certificate
actually chaining back to this server's CA. Skipped automatically if the
parent package isn't importable (see conftest.py's sys.path shim), same
as test_e2e_with_existing_client.py.
"""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
import uvicorn

from conftest import PARENT_CLIENT_AVAILABLE, make_test_settings
from saas_job_api.main import create_app

pytestmark = pytest.mark.skipif(
    not PARENT_CLIENT_AVAILABLE, reason="parent repo's certificate_discovery_engine package is not importable"
)

HOST = "127.0.0.1"
PORT = 8798
BASE_URL = f"http://{HOST}:{PORT}"
ADMIN_USERNAME = "e2e-platform-admin"
ADMIN_PASSWORD = "e2e-correct-horse-battery-staple"


class ServerThread(threading.Thread):
    def __init__(self, app) -> None:
        super().__init__(daemon=True)
        config = uvicorn.Config(app=app, host=HOST, port=PORT, log_level="warning")
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        asyncio.run(self.server.serve())

    def wait_until_started(self, timeout: float = 5.0) -> None:
        start = time.monotonic()
        while not self.server.started:
            if time.monotonic() - start > timeout:
                raise RuntimeError("uvicorn server did not start in time")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(timeout=5.0)


@pytest.fixture
def live_server():
    app = create_app(
        settings=make_test_settings(
            bootstrap_admin_username=ADMIN_USERNAME,
            bootstrap_admin_password=ADMIN_PASSWORD,
        )
    )
    thread = ServerThread(app)
    thread.start()
    thread.wait_until_started()
    yield
    thread.stop()


async def test_real_registration_agent_registers_against_a_live_server(live_server):
    from certificate_discovery_engine.gateway_vm import (
        Ed25519IdentityKeyGenerator,
        RegistrationAgent,
    )
    from certificate_discovery_engine.gateway_vm.http_client import post_json

    class FakeEnrollmentTokenSource:
        def __init__(self, token: str) -> None:
            self.token = token

        def get_token(self) -> str:
            return self.token

    class FakeIdentityStore:
        """Stands in for LinuxKeyringIdentityStore, which needs a real Linux
        kernel keyring - this test proves the registration handshake, not
        the storage adapter (that's covered separately, see
        test_gateway_vm_registration_security.py in the parent repo)."""

        def __init__(self) -> None:
            self._data: bytes | None = None

        def has_credential(self) -> bool:
            return self._data is not None

        def save_credential(self, data: bytes) -> None:
            self._data = data

        def load_credential(self) -> bytes:
            assert self._data is not None
            return self._data

    class SystemClock:
        def utcnow(self):
            from datetime import datetime, timezone

            return datetime.now(timezone.utc)

        def monotonic(self) -> float:
            return time.monotonic()

    # Issue a real enrollment token from the live server, as an admin would.
    async with httpx.AsyncClient(base_url=BASE_URL) as admin_client:
        login_resp = await admin_client.post(
            "/admin/v1/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert login_resp.status_code == 200, login_resp.text
        jwt = login_resp.json()["accessToken"]

        token_resp = await admin_client.post(
            "/admin/v1/enrollment-tokens", headers={"Authorization": f"Bearer {jwt}"}
        )
        assert token_resp.status_code == 200, token_resp.text
        enrollment_token = token_resp.json()["token"]

    identity_store = FakeIdentityStore()
    agent = RegistrationAgent(
        enrollment_token_source=FakeEnrollmentTokenSource(enrollment_token),
        identity_store=identity_store,
        key_generator=Ed25519IdentityKeyGenerator(),
        register_url=f"{BASE_URL}/gateway/v1/register",
        clock=SystemClock(),
        http_post=lambda url, payload: post_json(url, payload),
    )

    result = await asyncio.to_thread(agent.ensure_registered, "gw-e2e-registration-001")

    assert result.gateway_id == "gw-e2e-registration-001"
    assert result.already_registered is False

    from cryptography import x509

    issued = x509.load_pem_x509_certificate(result.certificate_pem.encode("ascii"))
    ca_cert = x509.load_pem_x509_certificate(result.ca_certificate_pem.encode("ascii"))
    assert issued.issuer == ca_cert.subject
    ca_cert.public_key().verify(issued.signature, issued.tbs_certificate_bytes)  # raises if it doesn't chain

    # Calling ensure_registered again must short-circuit to the stored
    # identity, not attempt a second (now-consumed) enrollment token.
    second = await asyncio.to_thread(agent.ensure_registered, "gw-e2e-registration-001")
    assert second.already_registered is True
    assert second.certificate_pem == result.certificate_pem
