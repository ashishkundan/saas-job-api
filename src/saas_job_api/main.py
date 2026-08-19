"""FastAPI app factory for the reference SaaS Job API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI

from .config import Settings, settings as default_settings
from .domain import JobRecord
from .errors import install_exception_handlers
from .routers import admin, gateway
from .store import create_store, close_store, new_job_id, new_correlation_id
from .time_provider import Clock, RealClock


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

    @app.on_event("shutdown")
    async def shutdown_event():
        if app.state.store:
            await close_store(app.state.store)

    install_exception_handlers(app)
    app.include_router(gateway.router)
    app.include_router(admin.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
