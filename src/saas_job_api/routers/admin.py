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
from ..models.admin import AdminCreateJobRequest, FaultInjectionRequest
from ..store import new_correlation_id, new_job_id
from ..store_base import JobStoreBase

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


def get_store(request: Request) -> JobStoreBase:
    return request.app.state.store


@router.post("/jobs")
async def create_job(body: AdminCreateJobRequest, store: JobStoreBase = Depends(get_store)):
    record = JobRecord(
        job_id=body.job_id or new_job_id(),
        job_type=body.job_type,
        manifest_version=body.manifest_version,
        priority=body.priority,
        scheduled_at=body.scheduled_at or datetime.now(timezone.utc),
        correlation_id=body.correlation_id or new_correlation_id(),
        payload=body.payload,
        max_attempts=body.max_attempts,
        trace_id=body.trace_id,
    )
    await store.seed(record)
    return {"jobId": record.job_id, "state": record.state.value}


@router.get("/jobs")
async def list_jobs(store: JobStoreBase = Depends(get_store)):
    records = await store.list_all()
    return [
        {
            "jobId": r.job_id,
            "jobType": r.job_type,
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
