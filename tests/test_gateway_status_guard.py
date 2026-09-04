"""Developer Implementation Guide §24: POST /gateway/v1/jobs/poll holds
jobs (returns them un-reserved) for a gateway whose own GatewayStatus has
decayed to UNREACHABLE/FAILED, wired in Phase 2.5 alongside the Tenant/
Target/Schedule model."""

from __future__ import annotations

from datetime import timedelta

from conftest import DEV_GATEWAY_ID

from saas_job_api.health import GatewayStatus, HealthState

POLL_BODY = {"maxJobs": 20}


async def _seed_job(client, admin_headers, **overrides):
    body = {"jobType": "TLS_SCAN", "manifestVersion": "1.0"}
    body.update(overrides)
    resp = await client.post("/admin/jobs", json=body, headers=admin_headers)
    assert resp.status_code == 200
    return resp.json()["jobId"]


async def _seed_status(app, *, last_heartbeat_at, last_reported_status=None) -> None:
    await app.state.health_store.upsert(
        GatewayStatus(
            gateway_id=DEV_GATEWAY_ID,
            tenant_id=None,
            last_heartbeat_at=last_heartbeat_at,
            gateway_version="1.0",
            container_runtime_status="UP",
            last_successful_job_at=None,
            last_error=None,
            last_reported_status=last_reported_status,
        )
    )


async def test_poll_holds_jobs_for_a_gateway_with_no_heartbeat_history(client, admin_headers, gateway_headers) -> None:
    # Fail open: a gateway that has never sent a heartbeat has no
    # GatewayStatus row at all - withholding all jobs from every
    # not-yet-heartbeated gateway would be a worse default than this rule
    # actually asks for.
    await _seed_job(client, admin_headers)

    resp = await client.post("/gateway/v1/jobs/poll", json=POLL_BODY, headers=gateway_headers)

    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1


async def test_poll_returns_jobs_for_a_healthy_gateway(client, admin_headers, gateway_headers, app, clock) -> None:
    await _seed_job(client, admin_headers)
    await _seed_status(app, last_heartbeat_at=clock.now())

    resp = await client.post("/gateway/v1/jobs/poll", json=POLL_BODY, headers=gateway_headers)

    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1


async def test_poll_returns_jobs_for_a_degraded_gateway(client, admin_headers, gateway_headers, app, clock) -> None:
    # DEGRADED is explicitly not held - only UNREACHABLE/FAILED are, per §24.
    await _seed_job(client, admin_headers)
    await _seed_status(app, last_heartbeat_at=clock.now() - timedelta(seconds=120))  # > 90s degraded threshold

    resp = await client.post("/gateway/v1/jobs/poll", json=POLL_BODY, headers=gateway_headers)

    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) == 1


async def test_poll_holds_jobs_for_an_unreachable_gateway(client, admin_headers, gateway_headers, app, clock) -> None:
    job_id = await _seed_job(client, admin_headers)
    await _seed_status(app, last_heartbeat_at=clock.now() - timedelta(seconds=400))  # > 300s unreachable threshold

    resp = await client.post("/gateway/v1/jobs/poll", json=POLL_BODY, headers=gateway_headers)

    assert resp.status_code == 204

    listing = await client.get("/admin/jobs", headers=admin_headers)
    job = next(j for j in listing.json() if j["jobId"] == job_id)
    assert job["state"] == "AVAILABLE"  # never reserved


async def test_poll_holds_jobs_for_a_gateway_past_the_failed_threshold(client, admin_headers, gateway_headers, app, clock) -> None:
    await _seed_job(client, admin_headers)
    await _seed_status(app, last_heartbeat_at=clock.now() - timedelta(seconds=2000))  # > 1800s failed threshold

    resp = await client.post("/gateway/v1/jobs/poll", json=POLL_BODY, headers=gateway_headers)

    assert resp.status_code == 204


async def test_poll_holds_jobs_for_a_gateway_that_explicitly_reported_failed(client, admin_headers, gateway_headers, app, clock) -> None:
    # last_reported_status=FAILED overrides the timing-derived state
    # immediately, even with a very recent heartbeat (health.py's own rule).
    await _seed_job(client, admin_headers)
    await _seed_status(app, last_heartbeat_at=clock.now(), last_reported_status=HealthState.FAILED)

    resp = await client.post("/gateway/v1/jobs/poll", json=POLL_BODY, headers=gateway_headers)

    assert resp.status_code == 204
