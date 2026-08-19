from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from saas_job_api.config import Settings
from saas_job_api.main import create_app
from saas_job_api.time_provider import FakeClock

DEV_TOKEN = "test-gateway-token"
DEV_GATEWAY_ID = "gw_test"
ADMIN_TOKEN = "test-admin-token"

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
        "admin_token": ADMIN_TOKEN,
        "reservation_ttl_seconds": 60.0,
        "database_url": os.environ.get("SAAS_JOB_API_TEST_DATABASE_URL"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def app(clock: FakeClock):
    return create_app(settings=make_test_settings(), clock=clock)


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
