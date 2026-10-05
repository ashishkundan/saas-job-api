"""FastAPI app factory for the reference SaaS Job API."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI

from .certs import CertificateAuthority, generate_ca
from .config import Settings, settings as default_settings
from .domain import JobRecord
from .errors import install_exception_handlers
from .health_store_memory import MemoryHealthStore
from .health_store_postgres import PostgresHealthStore
from .audit_retention import AuditRetentionSweeper
from .audit_store_memory import MemoryAuditLogStore
from .audit_store_postgres import PostgresAuditLogStore
from .gateway_operational_config_store_memory import MemoryGatewayOperationalConfigStore
from .gateway_operational_config_store_postgres import PostgresGatewayOperationalConfigStore
from .identity import AdminPrincipal, AdminRole
from .inventory_store_memory import MemoryInventoryStore
from .inventory_store_postgres import PostgresInventoryStore
from .orchestrator.scheduler_tick import start_scheduler_loop
from .passwords import hash_password
from .rbac_store_memory import MemoryRbacStore
from .rbac_store_postgres import PostgresRbacStore
from .registration_store_memory import MemoryRegistrationStore
from .registration_store_postgres import PostgresRegistrationStore
from .routers import admin, admin_auth, audit, gateway, gateway_config, heartbeat, registration, results, schedules, targets, tenants
from .schedule_store_memory import MemoryScheduleStore
from .schedule_store_postgres import PostgresScheduleStore
from .store import create_store, close_store, new_job_id, new_correlation_id
from .target_store_memory import MemoryTargetStore
from .target_store_postgres import PostgresTargetStore
from .tenant_store_memory import MemoryTenantStore
from .tenant_store_postgres import PostgresTenantStore
from .time_provider import Clock, RealClock

logger = logging.getLogger(__name__)


def _build_certificate_authority(cfg: Settings) -> CertificateAuthority:
    if cfg.ca_private_key_pem and cfg.ca_certificate_pem:
        key_pem = cfg.ca_private_key_pem.encode("utf-8")
        cert_pem = cfg.ca_certificate_pem.encode("utf-8")
    else:
        logger.warning(
            "no CA configured (SAAS_JOB_API_CA_PRIVATE_KEY_PEM / _CA_CERTIFICATE_PEM) - "
            "generating an ephemeral CA. Every previously-issued gateway certificate "
            "will stop validating against this instance on the next restart. "
            "Dev/test only - production must configure a persistent CA."
        )
        key_pem, cert_pem = generate_ca()
    return CertificateAuthority(key_pem, cert_pem, validity_days=cfg.gateway_certificate_validity_days)


async def _bootstrap_admin_principal(rbac_store, cfg: Settings) -> None:
    if not cfg.bootstrap_admin_username or not cfg.bootstrap_admin_password:
        return
    if await rbac_store.get_by_username(cfg.bootstrap_admin_username) is not None:
        return
    await rbac_store.create_principal(
        AdminPrincipal(
            principal_id=str(uuid.uuid4()),
            username=cfg.bootstrap_admin_username,
            password_hash=hash_password(cfg.bootstrap_admin_password),
            role=AdminRole.PLATFORM_ADMIN,
            created_at=datetime.now(timezone.utc),
        )
    )


async def _load_seed_file(store, path: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in data:
        record = JobRecord(
            job_id=item.get("jobId") or new_job_id(),
            job_type=item["jobType"],
            manifest_version=item["manifestVersion"],
            priority=item.get("priority", 50),
            scheduled_at=datetime.fromisoformat(item["scheduledAt"]) if item.get("scheduledAt") else datetime.now(timezone.utc),
            correlation_id=item.get("correlationId") or new_correlation_id(),
            payload=item.get("payload", {}),
            max_attempts=item.get("maxAttempts", 8),
            trace_id=item.get("traceId"),
        )
        await store.seed(record)


def create_app(*, settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    cfg = settings or default_settings
    app = FastAPI(title="SaaS Job API (reference implementation)")
    app.state.settings = cfg
    app.state.clock = clock or RealClock()
    app.state.store = None  # Will be initialized in startup event

    @app.on_event("startup")
    async def startup_event():
        app.state.store = await create_store(cfg, clock=app.state.clock)
        if cfg.seed_file:
            await _load_seed_file(app.state.store, cfg.seed_file)

        if cfg.database_url:
            from .db import get_pool

            pool = get_pool()
            app.state.registration_store = PostgresRegistrationStore(pool)
            app.state.rbac_store = PostgresRbacStore(pool)
            app.state.health_store = PostgresHealthStore(pool)
            app.state.tenant_store = PostgresTenantStore(pool)
            app.state.target_store = PostgresTargetStore(pool)
            app.state.schedule_store = PostgresScheduleStore(pool)
            app.state.inventory_store = PostgresInventoryStore(pool)
            app.state.audit_store = PostgresAuditLogStore(pool)
            app.state.gateway_operational_config_store = PostgresGatewayOperationalConfigStore(pool)
        else:
            app.state.registration_store = MemoryRegistrationStore()
            app.state.rbac_store = MemoryRbacStore()
            app.state.health_store = MemoryHealthStore()
            app.state.tenant_store = MemoryTenantStore()
            app.state.target_store = MemoryTargetStore()
            app.state.schedule_store = MemoryScheduleStore()
            app.state.inventory_store = MemoryInventoryStore()
            app.state.audit_store = MemoryAuditLogStore()
            app.state.gateway_operational_config_store = MemoryGatewayOperationalConfigStore()

        app.state.ca = _build_certificate_authority(cfg)
        await _bootstrap_admin_principal(app.state.rbac_store, cfg)

        app.state.scheduler_shutdown_event = asyncio.Event()
        app.state.scheduler_task = None
        if cfg.scheduler_enabled:
            app.state.scheduler_task = asyncio.create_task(
                start_scheduler_loop(
                    schedule_store=app.state.schedule_store,
                    target_store=app.state.target_store,
                    job_store=app.state.store,
                    health_store=app.state.health_store,
                    clock=app.state.clock,
                    shutdown_event=app.state.scheduler_shutdown_event,
                    interval_seconds=cfg.scheduler_tick_interval_seconds,
                    orphaned_job_sla_seconds=cfg.orphaned_job_sla_seconds,
                    gateway_degraded_after_seconds=cfg.gateway_degraded_after_seconds,
                    gateway_unreachable_after_seconds=cfg.gateway_unreachable_after_seconds,
                    gateway_failed_after_seconds=cfg.gateway_failed_after_seconds,
                )
            )

        app.state.audit_retention_shutdown_event = asyncio.Event()
        app.state.audit_retention_task = None
        if cfg.audit_retention_sweep_enabled:
            sweeper = AuditRetentionSweeper(
                store=app.state.audit_store,
                clock=app.state.clock,
                retention_days=cfg.audit_retention_days,
                batch_size=cfg.audit_retention_sweep_batch_size,
                interval_seconds=cfg.audit_retention_sweep_interval_seconds,
            )
            app.state.audit_retention_task = asyncio.create_task(sweeper.run(app.state.audit_retention_shutdown_event))

    @app.on_event("shutdown")
    async def shutdown_event():
        if app.state.scheduler_task is not None:
            app.state.scheduler_shutdown_event.set()
            await app.state.scheduler_task
        if app.state.audit_retention_task is not None:
            app.state.audit_retention_shutdown_event.set()
            await app.state.audit_retention_task
        if app.state.store:
            await close_store(app.state.store)

    install_exception_handlers(app)
    app.include_router(gateway.router)
    app.include_router(gateway_config.router)
    app.include_router(admin.router)
    app.include_router(registration.admin_router)
    app.include_router(registration.gateway_router)
    app.include_router(admin_auth.router)
    app.include_router(heartbeat.router)
    app.include_router(tenants.router)
    app.include_router(targets.router)
    app.include_router(schedules.router)
    app.include_router(results.router)
    app.include_router(audit.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
