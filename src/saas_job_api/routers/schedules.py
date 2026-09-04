"""Schedule CRUD (Phase 2.5), nested under a tenant. Same RBAC shape as
targets.py (create/delete: platform_admin or tenant_admin; read: any
authenticated principal), plus validating that target_id actually belongs
to this tenant before a schedule can be created against it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import authenticated_admin_principal, require_any_role, require_tenant_access
from ..errors import BadRequestError, ConflictError, NotFoundError
from ..identity import AdminRole
from ..jwt_tokens import TokenClaims
from ..models.tenancy import ScheduleCreateRequest, ScheduleResponse
from ..schedule_store_base import ScheduleStoreBase
from ..target_store_base import TargetStoreBase
from ..tenancy import Schedule, new_schedule_id
from ..time_provider import Clock

router = APIRouter(prefix="/admin/v1/tenants/{tenant_id}/schedules", tags=["schedules"])

_WRITE_ROLES = (AdminRole.PLATFORM_ADMIN, AdminRole.TENANT_ADMIN)


def get_schedule_store(request: Request) -> ScheduleStoreBase:
    return request.app.state.schedule_store


def get_target_store(request: Request) -> TargetStoreBase:
    return request.app.state.target_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def _to_response(schedule: Schedule) -> ScheduleResponse:
    return ScheduleResponse(
        scheduleId=schedule.schedule_id,
        tenantId=schedule.tenant_id,
        targetId=schedule.target_id,
        jobType=schedule.job_type,
        manifestVersion=schedule.manifest_version,
        intervalSeconds=schedule.interval_seconds,
        nextRunAt=schedule.next_run_at,
        enabled=schedule.enabled,
        lastRunAt=schedule.last_run_at,
        createdAt=schedule.created_at,
    )


@router.post("", response_model=ScheduleResponse)
async def create_schedule(
    tenant_id: str,
    body: ScheduleCreateRequest,
    schedule_store: ScheduleStoreBase = Depends(get_schedule_store),
    target_store: TargetStoreBase = Depends(get_target_store),
    clock: Clock = Depends(get_clock),
    claims: TokenClaims = Depends(require_any_role(*_WRITE_ROLES)),
) -> ScheduleResponse:
    require_tenant_access(claims, tenant_id)

    if body.interval_seconds <= 0:
        raise BadRequestError("intervalSeconds must be a positive integer")

    target = await target_store.get(tenant_id, body.target_id)
    if target is None:
        raise NotFoundError(f"target not found for this tenant: {body.target_id}")

    now = clock.now()
    schedule = Schedule(
        schedule_id=body.schedule_id or new_schedule_id(),
        tenant_id=tenant_id,
        target_id=body.target_id,
        job_type=body.job_type,
        manifest_version=body.manifest_version,
        interval_seconds=body.interval_seconds,
        next_run_at=body.next_run_at or now,
        created_at=now,
    )
    try:
        await schedule_store.create(schedule)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return _to_response(schedule)


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    tenant_id: str,
    store: ScheduleStoreBase = Depends(get_schedule_store),
    claims: TokenClaims = Depends(authenticated_admin_principal),
) -> list[ScheduleResponse]:
    require_tenant_access(claims, tenant_id)
    schedules = await store.list_by_tenant(tenant_id)
    return [_to_response(s) for s in schedules]


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    tenant_id: str,
    schedule_id: str,
    store: ScheduleStoreBase = Depends(get_schedule_store),
    claims: TokenClaims = Depends(authenticated_admin_principal),
) -> ScheduleResponse:
    require_tenant_access(claims, tenant_id)
    schedule = await store.get(tenant_id, schedule_id)
    if schedule is None:
        raise NotFoundError(f"schedule not found: {schedule_id}")
    return _to_response(schedule)


@router.delete("/{schedule_id}")
async def delete_schedule(
    tenant_id: str,
    schedule_id: str,
    store: ScheduleStoreBase = Depends(get_schedule_store),
    claims: TokenClaims = Depends(require_any_role(*_WRITE_ROLES)),
) -> dict[str, str]:
    require_tenant_access(claims, tenant_id)
    await store.delete(tenant_id, schedule_id)
    return {"status": "deleted", "scheduleId": schedule_id}
