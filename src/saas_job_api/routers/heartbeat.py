"""POST /gateway/v1/heartbeat (Phase 1.4).

Gateway-authenticated via the existing bearer-token dependency
(authenticated_gateway), the same mechanism poll/received already use -
NOT yet migrated to verifying the Registration Agent's mTLS certificate
(1.1/1.1b). True edge mTLS enforcement depends on deployment topology
(a TLS-terminating proxy that forwards the verified client cert, or
uvicorn terminating TLS directly) which isn't settled for this reference
app; migrating all gateway-facing endpoints to cert-based auth is a
distinct, larger cross-cutting change flagged for later, not bundled in
here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import authenticated_gateway, bind_gateway_id, get_settings
from ..config import Settings
from ..errors import BadRequestError
from ..health import GatewayStatus, HealthState, derive_current_status
from ..health_store_base import HealthStoreBase
from ..models.heartbeat import HeartbeatRequest, HeartbeatResponse
from ..time_provider import Clock

router = APIRouter(prefix="/gateway/v1", tags=["heartbeat"])


def get_health_store(request: Request) -> HealthStoreBase:
    return request.app.state.health_store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def receive_heartbeat(
    body: HeartbeatRequest,
    store: HealthStoreBase = Depends(get_health_store),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
    gateway_id: str = Depends(authenticated_gateway),
) -> HeartbeatResponse:
    bind_gateway_id(body.gateway_id, gateway_id)

    try:
        reported_status = HealthState(body.status)
    except ValueError as exc:
        raise BadRequestError(f"unknown heartbeat status '{body.status}'") from exc

    now = clock.now()
    existing = await store.get(gateway_id)
    status = GatewayStatus(
        gateway_id=gateway_id,
        tenant_id=existing.tenant_id if existing else None,
        last_heartbeat_at=body.timestamp,
        gateway_version=body.gateway_version or (existing.gateway_version if existing else None),
        container_runtime_status=body.container_runtime,
        # Not part of the heartbeat schema (they come from job execution
        # outcomes, wired in a later phase) - preserve whatever was there.
        last_successful_job_at=existing.last_successful_job_at if existing else None,
        last_error=existing.last_error if existing else None,
        last_reported_status=reported_status,
    )
    await store.upsert(status)

    current_status = derive_current_status(
        status,
        now=now,
        degraded_after_seconds=settings.gateway_degraded_after_seconds,
        unreachable_after_seconds=settings.gateway_unreachable_after_seconds,
        failed_after_seconds=settings.gateway_failed_after_seconds,
    )
    return HeartbeatResponse(gatewayId=gateway_id, currentStatus=current_status.value)
