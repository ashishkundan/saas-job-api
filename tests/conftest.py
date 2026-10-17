from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from saas_job_api.config import Settings
from saas_job_api.main import create_app
from saas_job_api.tenancy import Target, Tenant
from saas_job_api.time_provider import FakeClock

DEV_TOKEN = "test-gateway-token"
DEV_GATEWAY_ID = "gw_test"
ADMIN_TOKEN = "test-admin-token"
# The fixture tenant DEV_GATEWAY_ID belongs to, and one managed Target in
# it. Jobs created via POST /admin/jobs must name a tenant + target.
TEST_TENANT_ID = "tenant-fixture"
TEST_TARGET_ID = "target-fixture"
TEST_PLUGIN_REF = "tls-scanner"
TEST_JOB_TYPE = "tls-scanner-scan"

# Repo is nested at <parent>/saas-job-api; the parent's importable package root is <parent>/src.
PARENT_SRC = Path(__file__).resolve().parents[2] / "src"
if PARENT_SRC.is_dir() and str(PARENT_SRC) not in sys.path:
    sys.path.insert(0, str(PARENT_SRC))

try:
    import certificate_discovery_engine  # noqa: F401

    PARENT_CLIENT_AVAILABLE = True
except ImportError:
    PARENT_CLIENT_AVAILABLE = False


def make_test_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "gateway_tokens_json": json.dumps({DEV_TOKEN: DEV_GATEWAY_ID}),
        "gateway_tenants_json": json.dumps({DEV_GATEWAY_ID: TEST_TENANT_ID}),
        "admin_token": ADMIN_TOKEN,
        "reservation_ttl_seconds": 60.0,
        "database_url": os.environ.get("SAAS_JOB_API_TEST_DATABASE_URL"),
        # Tests that specifically exercise scheduler_tick.py enable this
        # explicitly; every other test would otherwise spin up an unused
        # background task per app fixture for no reason.
        "scheduler_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


async def seed_fixture_tenant_and_target(app, *, tenant_id: str = TEST_TENANT_ID, target_id: str = TEST_TARGET_ID) -> None:
    """Create the tenant + Target that test jobs are created against."""
    now = app.state.clock.now()
    if await app.state.tenant_store.get(tenant_id) is None:
        await app.state.tenant_store.create(Tenant(tenant_id=tenant_id, name=tenant_id, created_at=now))
    if await app.state.target_store.get(tenant_id, target_id) is None:
        await app.state.target_store.create(
            Target(
                target_id=target_id,
                tenant_id=tenant_id,
                name=target_id,
                host="192.0.2.10",
                port=443,
                plugin_ref=TEST_PLUGIN_REF,
                plugin_version="1.0",
                created_at=now,
            )
        )


def job_body(**overrides: object) -> dict[str, object]:
    """A valid POST /admin/jobs body for the fixture tenant/target."""
    body: dict[str, object] = {"tenantId": TEST_TENANT_ID, "targetId": TEST_TARGET_ID}
    body.update(overrides)
    return body


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def app(clock: FakeClock):
    app = create_app(settings=make_test_settings(), clock=clock)
    # httpx.ASGITransport in this environment does not run ASGI lifespan hooks,
    # so tests must trigger startup/shutdown explicitly.
    async with app.router.lifespan_context(app):
        await seed_fixture_tenant_and_target(app)
        yield app


@pytest.fixture
async def client(app):
    # raise_app_exceptions=False: an unhandled exception should surface as the
    # HTTP response our own exception handlers produce (matching real client
    # behavior over a real socket), not propagate as a Python exception in the test.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def gateway_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {DEV_TOKEN}"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}
