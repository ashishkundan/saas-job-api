"""Opt-in verification that the parent repo's real GatewayHealthManager +
HttpHeartbeatSink can send a heartbeat to a live instance of this server
end-to-end, proving the wire format actually matches on both sides (field
names, aliases, status enum values) rather than just inspection. Skipped
automatically if the parent package isn't importable, same as the other
test_e2e_*.py files.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
import uvicorn

from conftest import PARENT_CLIENT_AVAILABLE, make_test_settings
from saas_job_api.main import create_app

pytestmark = pytest.mark.skipif(
    not PARENT_CLIENT_AVAILABLE, reason="parent repo's certificate_discovery_engine package is not importable"
)

HOST = "127.0.0.1"
PORT = 8797
BASE_URL = f"http://{HOST}:{PORT}"
DEV_TOKEN = "e2e-heartbeat-gateway-token"
DEV_GATEWAY_ID = "gw-e2e-heartbeat-001"


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
        settings=make_test_settings(gateway_tokens_json=json.dumps({DEV_TOKEN: DEV_GATEWAY_ID}))
    )
    thread = ServerThread(app)
    thread.start()
    thread.wait_until_started()
    yield app
    thread.stop()


async def test_real_health_manager_sends_a_heartbeat_to_a_live_server(live_server):
    from certificate_discovery_engine.gateway_vm import (
        GatewayHealthManager,
        HealthState,
        HttpHeartbeatSink,
    )

    class FixedComponentCheck:
        def __init__(self, status: str) -> None:
            self.status = status

        def check(self) -> str:
            return self.status

    class FixedResourceCheck:
        def __init__(self, percent: float) -> None:
            self.percent = percent

        def usage_percent(self) -> float:
            return self.percent

    class SystemClock:
        def utcnow(self):
            from datetime import datetime, timezone

            return datetime.now(timezone.utc)

        def monotonic(self) -> float:
            return time.monotonic()

    manager = GatewayHealthManager(
        gateway_id=DEV_GATEWAY_ID,
        component_checks={
            "job_poller": FixedComponentCheck("UP"),
            "core_service": FixedComponentCheck("UP"),
            "plugin_orchestrator": FixedComponentCheck("UP"),
            "container_runtime": FixedComponentCheck("UP"),
        },
        cpu_check=FixedResourceCheck(15.0),
        memory_check=FixedResourceCheck(40.0),
        disk_check=FixedResourceCheck(55.0),
        clock=SystemClock(),
    )
    heartbeat = manager.collect()
    assert heartbeat.status == HealthState.HEALTHY

    sink = HttpHeartbeatSink(heartbeat_url=f"{BASE_URL}/gateway/v1/heartbeat", api_token=DEV_TOKEN)

    # HttpHeartbeatSink.send() returns None (fire-and-forget from the
    # Health Manager's perspective) - confirm it doesn't raise, then read
    # the stored record straight from the live app's own store to prove
    # the real endpoint actually persisted what the real sink sent.
    await sink.send(heartbeat)

    stored = await live_server.state.health_store.get(DEV_GATEWAY_ID)
    assert stored is not None
    assert stored.container_runtime_status == "UP"
    assert stored.last_reported_status == "HEALTHY"
