"""The two SaaS Job API endpoints from TDD §9, plus a legacy compatibility alias.

POST /gateway/v1/jobs/received (flat body, no path jobId) exists only because
the parent repo's current HttpJobSource.acknowledge_received() always POSTs to
a single flat URL with jobId in the body -- it never path-templates {jobId}.
It is not part of TDD §9.2; see saas-job-api/README.md "Known contract gaps".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response

from ..auth import authenticated_gateway, bind_gateway_id, get_settings
from ..errors import BadRequestError
from ..models.poll import Job, PollRequest, PollResponse
from ..models.received import ReceivedRequest, ReceivedResponse
from ..store import JobStore

router = APIRouter(prefix="/gateway/v1/jobs", tags=["gateway"])


def get_store(request: Request) -> JobStore:
    return request.app.state.store


@router.post("/poll", response_model=None)
async def poll_jobs(
    body: PollRequest,
    request: Request,
    store: JobStore = Depends(get_store),
    gateway_id: str = Depends(authenticated_gateway),
):
    bind_gateway_id(body.gateway_id, gateway_id)

    fault = await store.take_fault()
    if fault is not None:
        headers = {}
        if fault.retry_after_seconds is not None:
            headers["Retry-After"] = str(int(fault.retry_after_seconds))
        return Response(status_code=fault.status_code, headers=headers)

    settings = get_settings(request)
    now = store.clock.now()
    chosen = await store.claim(
        gateway_id=gateway_id,
        job_types=body.supported_job_types,
        manifest_versions=body.supported_manifest_versions,
        max_jobs=body.max_jobs,
        dispatch_slots=body.available_dispatch_slots,
    )

    if not chosen:
        return Response(status_code=204)

    jobs = [
        Job(
            jobId=job.job_id,
            jobType=job.job_type,
            manifestVersion=job.manifest_version,
            priority=job.priority,
            scheduledAt=job.scheduled_at,
            receiptToken=job.receipt_token,
            correlationId=job.correlation_id,
            payload=job.payload,
            maxAttempts=job.max_attempts,
            traceId=job.trace_id,
        )
        for job in chosen
    ]
    reservation_until = min(job.reservation_until for job in chosen)
    response = PollResponse(
        requestId=body.request_id or str(uuid.uuid4()),
        serverTime=now,
        receivedAt=now,
        pollAfterMs=settings.default_poll_after_ms,
        reservationUntil=reservation_until,
        jobs=jobs,
    )
    return response.model_dump(by_alias=True, mode="json")


async def _acknowledge(
    job_id: str,
    body: ReceivedRequest,
    store: JobStore,
    gateway_id: str,
) -> ReceivedResponse:
    bind_gateway_id(body.gateway_id, gateway_id)
    job = await store.acknowledge(
        job_id=job_id,
        gateway_id=gateway_id,
        receipt_token=body.receipt_token,
        received_at=body.received_at,
        payload_hash=body.payload_hash,
        local_record_version=body.local_record_version,
    )
    return ReceivedResponse(jobId=job.job_id)


@router.post("/{job_id}/received", response_model=ReceivedResponse)
async def acknowledge_received(
    job_id: str,
    body: ReceivedRequest,
    store: JobStore = Depends(get_store),
    gateway_id: str = Depends(authenticated_gateway),
) -> ReceivedResponse:
    return await _acknowledge(job_id, body, store, gateway_id)


@router.post("/received", response_model=ReceivedResponse)
async def acknowledge_received_legacy_alias(
    body: ReceivedRequest,
    store: JobStore = Depends(get_store),
    gateway_id: str = Depends(authenticated_gateway),
) -> ReceivedResponse:
    if body.job_id is None:
        raise BadRequestError("jobId is required in the request body for the legacy alias route")
    return await _acknowledge(body.job_id, body, store, gateway_id)
