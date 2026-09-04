from __future__ import annotations

from datetime import datetime, timedelta, timezone

from saas_job_api.health import GatewayStatus, HealthState


def _heartbeat_body(**overrides) -> dict:
    body = {
        "status": "HEALTHY",
        "coreService": "UP",
        "jobPoller": "UP",
        "pluginOrchestrator": "UP",
        "containerRuntime": "UP",
        "cpuUsage": 12.5,
        "memoryUsage": 33.0,
        "diskUsage": 44.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body.update(overrides)
    return body


async def test_heartbeat_requires_authentication(client) -> None:
    resp = await client.post("/gateway/v1/heartbeat", json=_heartbeat_body())

    assert resp.status_code == 401


async def test_heartbeat_accepted_returns_healthy_for_a_fresh_heartbeat(client, gateway_headers, clock) -> None:
    resp = await client.post(
        "/gateway/v1/heartbeat",
        json=_heartbeat_body(timestamp=clock.now().isoformat()),
        headers=gateway_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["gatewayId"] == "gw_test"
    assert body["currentStatus"] == "HEALTHY"


async def test_heartbeat_rejects_unknown_status(client, gateway_headers) -> None:
    resp = await client.post(
        "/gateway/v1/heartbeat",
        json=_heartbeat_body(status="NOT_A_REAL_STATUS"),
        headers=gateway_headers,
    )

    assert resp.status_code == 400


async def test_heartbeat_rejects_gateway_id_mismatch(client, gateway_headers) -> None:
    resp = await client.post(
        "/gateway/v1/heartbeat",
        json=_heartbeat_body(gatewayId="some-other-gateway"),
        headers=gateway_headers,
    )

    assert resp.status_code == 403


async def test_heartbeat_reflects_degraded_when_reported_timestamp_is_stale(client, gateway_headers, clock) -> None:
    """End-to-end through the real endpoint: a heartbeat reporting a
    timestamp already past the degraded threshold relative to the server's
    clock comes back DEGRADED, not HEALTHY."""
    stale_timestamp = clock.now() - timedelta(seconds=100)  # past the 90s default threshold

    resp = await client.post(
        "/gateway/v1/heartbeat",
        json=_heartbeat_body(timestamp=stale_timestamp.isoformat()),
        headers=gateway_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStatus"] == "DEGRADED"


async def test_heartbeat_explicit_failed_report_overrides_a_fresh_timestamp(client, gateway_headers, clock) -> None:
    resp = await client.post(
        "/gateway/v1/heartbeat",
        json=_heartbeat_body(status="FAILED", timestamp=clock.now().isoformat()),
        headers=gateway_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["currentStatus"] == "FAILED"


async def test_heartbeat_preserves_fields_not_in_the_heartbeat_schema(app, client, gateway_headers, clock) -> None:
    """last_successful_job_at/last_error come from job execution outcomes
    (wired in a later phase), not the heartbeat payload itself - a new
    heartbeat must not wipe them out."""
    existing = GatewayStatus(
        gateway_id="gw_test",
        tenant_id="tenant-1",
        last_heartbeat_at=clock.now() - timedelta(seconds=500),
        gateway_version="0.9",
        container_runtime_status="UP",
        last_successful_job_at=clock.now() - timedelta(hours=1),
        last_error="previous transient error",
        last_reported_status=HealthState.DEGRADED,
    )
    await app.state.health_store.upsert(existing)

    resp = await client.post(
        "/gateway/v1/heartbeat",
        json=_heartbeat_body(timestamp=clock.now().isoformat()),
        headers=gateway_headers,
    )
    assert resp.status_code == 200, resp.text

    stored = await app.state.health_store.get("gw_test")
    assert stored.tenant_id == "tenant-1"
    assert stored.last_successful_job_at == existing.last_successful_job_at
    assert stored.last_error == "previous transient error"
