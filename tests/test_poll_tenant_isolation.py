"""A gateway only ever receives jobs for its own tenant (customer).

Two gateways in two tenants poll the same SaaS; each must see only its own
tenant's jobs. A gateway with no tenant, or whose registered identity and
configured tenant disagree, is refused outright.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from conftest import ADMIN_TOKEN, job_body, make_test_settings, seed_fixture_tenant_and_target
from saas_job_api.identity import GatewayIdentity
from saas_job_api.main import create_app

TOKEN_A, GATEWAY_A, TENANT_A, TARGET_A = "token-a", "gw_a", "tenant-a", "target-a"
TOKEN_B, GATEWAY_B, TENANT_B, TARGET_B = "token-b", "gw_b", "tenant-b", "target-b"
TOKEN_NONE, GATEWAY_NONE = "token-none", "gw_unbound"
ADMIN = {"X-Admin-Token": ADMIN_TOKEN}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _Lab:
    def __init__(self, app, client) -> None:
        self.app = app
        self.client = client

    async def create_job(self, tenant_id: str, target_id: str) -> str:
        resp = await self.client.post("/admin/jobs", json=job_body(tenantId=tenant_id, targetId=target_id), headers=ADMIN)
        assert resp.status_code == 200, resp.text
        return resp.json()["jobId"]

    async def poll(self, token: str) -> httpx.Response:
        return await self.client.post("/gateway/v1/jobs/poll", json={"maxJobs": 20}, headers=_bearer(token))


async def _with_lab(test) -> None:
    app = create_app(
        settings=make_test_settings(
            gateway_tokens_json=json.dumps({TOKEN_A: GATEWAY_A, TOKEN_B: GATEWAY_B, TOKEN_NONE: GATEWAY_NONE}),
            gateway_tenants_json=json.dumps({GATEWAY_A: TENANT_A, GATEWAY_B: TENANT_B}),
        )
    )
    async with app.router.lifespan_context(app):
        await seed_fixture_tenant_and_target(app, tenant_id=TENANT_A, target_id=TARGET_A)
        await seed_fixture_tenant_and_target(app, tenant_id=TENANT_B, target_id=TARGET_B)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await test(_Lab(app, client))


async def test_each_gateway_receives_only_its_own_tenants_jobs() -> None:
    async def run(lab: _Lab) -> None:
        job_a = await lab.create_job(TENANT_A, TARGET_A)
        job_b = await lab.create_job(TENANT_B, TARGET_B)

        poll_a = await lab.poll(TOKEN_A)
        assert poll_a.status_code == 200
        assert [j["jobId"] for j in poll_a.json()["jobs"]] == [job_a]
        assert poll_a.json()["jobs"][0]["payload"]["tenantId"] == TENANT_A

        poll_b = await lab.poll(TOKEN_B)
        assert poll_b.status_code == 200
        assert [j["jobId"] for j in poll_b.json()["jobs"]] == [job_b]

    await _with_lab(run)


async def test_a_gateway_never_receives_another_tenants_job_even_when_its_own_queue_is_empty() -> None:
    async def run(lab: _Lab) -> None:
        job_b = await lab.create_job(TENANT_B, TARGET_B)

        assert (await lab.poll(TOKEN_A)).status_code == 204
        assert (await lab.app.state.store.get(job_b)).state.value == "AVAILABLE"

    await _with_lab(run)


async def test_a_gateway_with_no_tenant_is_refused() -> None:
    async def run(lab: _Lab) -> None:
        await lab.create_job(TENANT_A, TARGET_A)

        assert (await lab.poll(TOKEN_NONE)).status_code == 403

    await _with_lab(run)


async def test_a_registered_identity_tenant_that_disagrees_with_config_is_refused() -> None:
    async def run(lab: _Lab) -> None:
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        await lab.app.state.registration_store.upsert_gateway_identity(
            GatewayIdentity(
                gateway_id=GATEWAY_A,
                tenant_id=TENANT_B,
                public_key_fingerprint="fp",
                certificate_pem="pem",
                certificate_serial="serial",
                certificate_not_after=now,
                registered_at=now,
                last_rotated_at=now,
            )
        )
        await lab.create_job(TENANT_A, TARGET_A)
        await lab.create_job(TENANT_B, TARGET_B)

        assert (await lab.poll(TOKEN_A)).status_code == 403

    await _with_lab(run)


async def test_a_registered_identity_alone_binds_the_tenant() -> None:
    async def run(lab: _Lab) -> None:
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        await lab.app.state.registration_store.upsert_gateway_identity(
            GatewayIdentity(
                gateway_id=GATEWAY_NONE,
                tenant_id=TENANT_B,
                public_key_fingerprint="fp",
                certificate_pem="pem",
                certificate_serial="serial",
                certificate_not_after=now,
                registered_at=now,
                last_rotated_at=now,
            )
        )
        job_b = await lab.create_job(TENANT_B, TARGET_B)

        resp = await lab.poll(TOKEN_NONE)
        assert resp.status_code == 200
        assert [j["jobId"] for j in resp.json()["jobs"]] == [job_b]

    await _with_lab(run)


async def test_supported_job_types_filter_is_honored() -> None:
    async def run(lab: _Lab) -> None:
        await lab.create_job(TENANT_A, TARGET_A)

        resp = await lab.client.post(
            "/gateway/v1/jobs/poll",
            json={"maxJobs": 20, "supportedJobTypes": ["windows-collector-scan"]},
            headers=_bearer(TOKEN_A),
        )

        assert resp.status_code == 204

    await _with_lab(run)
