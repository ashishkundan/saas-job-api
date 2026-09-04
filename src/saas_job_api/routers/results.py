"""POST /gateway/v1/jobs/{jobId}/results + /interrupted (Phase 2.6).

Gateway-authenticated the same way poll/received already are
(authenticated_gateway), and bound to the job the same way acknowledge()
is - not via bind_gateway_id (there's no gatewayId to cross-check the
body against, since path-based routing already scopes to one job), but
via the store methods' own ack_gateway_id check: mark_completed()/
reissue_one() raise ConflictError / no-op respectively if the calling
gateway isn't the one that acknowledged this job.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from ..auth import authenticated_gateway
from ..errors import BadRequestError, NotFoundError
from ..inventory_store_base import InventoryStoreBase
from ..models.results import ReportInterruptedRequest, SubmitResultRequest, SubmitResultResponse
from ..store_base import JobStoreBase
from ..time_provider import Clock

router = APIRouter(prefix="/gateway/v1/jobs", tags=["results"])
logger = logging.getLogger(__name__)


def get_job_store(request: Request) -> JobStoreBase:
    return request.app.state.store


def get_inventory_store(request: Request) -> InventoryStoreBase:
    return request.app.state.inventory_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def _check_job_id(path_job_id: str, body_job_id: str | None) -> None:
    if body_job_id is not None and body_job_id != path_job_id:
        raise BadRequestError("jobId in body does not match jobId in path")


@router.post("/{job_id}/results", response_model=SubmitResultResponse)
async def submit_result(
    job_id: str,
    body: SubmitResultRequest,
    job_store: JobStoreBase = Depends(get_job_store),
    inventory_store: InventoryStoreBase = Depends(get_inventory_store),
    clock: Clock = Depends(get_clock),
    gateway_id: str = Depends(authenticated_gateway),
) -> SubmitResultResponse:
    _check_job_id(job_id, body.job_id)

    job = await job_store.get(job_id)
    if job is None:
        raise NotFoundError(f"unknown job: {job_id}")

    now = clock.now()

    # mark_completed() first, deliberately: it's the ownership check
    # (raises ConflictError if this gateway_id isn't who acknowledged the
    # job - e.g. it was already reissued to a different gateway) and it's
    # idempotent (a no-op if the job is already COMPLETED, the common case
    # on a retried submission). Doing this before writing to the inventory
    # store means a rejected/stale submission never leaves a phantom
    # inventory row behind for a job it no longer owns.
    await job_store.mark_completed(job_id=job_id, gateway_id=gateway_id, now=now)

    outcome = await inventory_store.submit_result(
        job_id=job_id,
        attempt_token=body.attempt_token,
        tenant_id=job.payload.get("tenantId"),
        target_id=job.payload.get("targetId"),
        plugin_id=body.plugin_id,
        plugin_version=body.plugin_version,
        certificates=[c.model_dump(by_alias=True) for c in body.certificates],
        received_at=now,
    )

    logger.info(
        "job_result_submitted",
        extra={
            "event": "job_result_submitted",
            "job_id": job_id,
            "gateway_id": gateway_id,
            "dedupe": outcome.dedupe,
            "record_count": outcome.record_count,
        },
    )

    return SubmitResultResponse(accepted=outcome.accepted, dedupe=outcome.dedupe, recordCount=outcome.record_count)


@router.post("/{job_id}/interrupted")
async def report_interrupted(
    job_id: str,
    body: ReportInterruptedRequest,
    job_store: JobStoreBase = Depends(get_job_store),
    clock: Clock = Depends(get_clock),
    gateway_id: str = Depends(authenticated_gateway),
) -> dict[str, str]:
    _check_job_id(job_id, body.job_id)

    reissued = await job_store.reissue_one(job_id=job_id, gateway_id=gateway_id, now=clock.now())

    logger.info(
        "job_interrupted_reported",
        extra={"event": "job_interrupted_reported", "job_id": job_id, "gateway_id": gateway_id, "reissued": reissued is not None},
    )

    return {"status": "reissued" if reissued is not None else "noop", "jobId": job_id}
