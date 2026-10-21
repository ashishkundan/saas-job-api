"""Dev/test-only endpoints: not part of the SaaS Job API contract.

Lets a test seed jobs, list/reset store state, and inject a one-shot poll
fault (429/5xx) so TDD §9.3's transient-failure paths can be exercised
without a real rate limiter.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from ..auth import require_admin_token
from ..domain import JobRecord
from ..errors import BadRequestError, NotFoundError
from ..models.admin import AdminCreateJobRequest, FaultInjectionRequest
from ..plugin_store_base import PluginStoreBase
from ..store import new_correlation_id, new_job_id
from ..store_base import JobStoreBase
from ..target_store_base import TargetStoreBase
from ..tenancy import build_target_job_payload, default_job_type, resolve_plugin_version
from ..tenant_store_base import TenantStoreBase

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


def get_store(request: Request) -> JobStoreBase:
    return request.app.state.store


def get_tenant_store(request: Request) -> TenantStoreBase:
    return request.app.state.tenant_store


def get_target_store(request: Request) -> TargetStoreBase:
    return request.app.state.target_store


def get_plugin_store(request: Request) -> PluginStoreBase:
    return request.app.state.plugin_store


@router.post("/jobs")
async def create_job(
    body: AdminCreateJobRequest,
    store: JobStoreBase = Depends(get_store),
    tenant_store: TenantStoreBase = Depends(get_tenant_store),
    target_store: TargetStoreBase = Depends(get_target_store),
    plugin_store: PluginStoreBase = Depends(get_plugin_store),
):
    tenant = await tenant_store.get(body.tenant_id)
    if tenant is None:
        raise NotFoundError(f"tenant not found: {body.tenant_id}")
    # Targets are looked up within the tenant, so another tenant's
    # targetId is indistinguishable from an unknown one.
    target = await target_store.get(body.tenant_id, body.target_id)
    if target is None:
        raise NotFoundError(f"target not found: {body.target_id}")

    pins = await plugin_store.pinned_versions(target.tenant_id)
    if target.plugin_ref not in pins:
        raise BadRequestError(f"tenant {target.tenant_id} is not entitled to plugin {target.plugin_ref}")
    plugin_version = resolve_plugin_version(target, pins[target.plugin_ref])
    if plugin_version is None:
        raise BadRequestError(
            f"target '{target.target_id}' has no pluginVersion and tenant {target.tenant_id} "
            f"has no pinned version of {target.plugin_ref}"
        )

    expected_job_type = default_job_type(target)
    if body.job_type is not None and body.job_type != expected_job_type:
        raise BadRequestError(
            f"jobType '{body.job_type}' does not match target '{target.target_id}' "
            f"(plugin '{target.plugin_ref}' runs as '{expected_job_type}')"
        )

    record = JobRecord(
        job_id=body.job_id or new_job_id(),
        job_type=expected_job_type,
        manifest_version=body.manifest_version,
        priority=body.priority,
        scheduled_at=body.scheduled_at or datetime.now(timezone.utc),
        correlation_id=body.correlation_id or new_correlation_id(),
        payload=build_target_job_payload(target, plugin_version=plugin_version, timeoutSeconds=body.timeout_seconds),
        max_attempts=body.max_attempts,
        trace_id=body.trace_id,
        tenant_id=target.tenant_id,
        target_id=target.target_id,
    )
    await store.seed(record)
    return {
        "jobId": record.job_id,
        "state": record.state.value,
        "jobType": record.job_type,
        "tenantId": record.tenant_id,
        "targetId": record.target_id,
    }


@router.get("/jobs")
async def list_jobs(tenantId: str | None = None, store: JobStoreBase = Depends(get_store)):
    records = await store.list_all()
    if tenantId is not None:
        records = [r for r in records if r.tenant_id == tenantId]
    return [
        {
            "jobId": r.job_id,
            "jobType": r.job_type,
            "tenantId": r.tenant_id,
            "targetId": r.target_id,
            "state": r.state.value,
            "reservedBy": r.reserved_by,
            "reservationUntil": r.reservation_until.isoformat() if r.reservation_until else None,
            "deliveryAttempts": r.delivery_attempts,
            "ackGatewayId": r.ack_gateway_id,
        }
        for r in records
    ]


@router.post("/reset")
async def reset(store: JobStoreBase = Depends(get_store)):
    await store.reset()
    return {"status": "reset"}


@router.post("/faults")
async def set_fault(body: FaultInjectionRequest, store: JobStoreBase = Depends(get_store)):
    await store.set_fault(body.next_poll_status, body.retry_after_seconds)
    return {"status": "armed", "nextPollStatus": body.next_poll_status}
