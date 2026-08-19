"""Factory for creating the appropriate job store implementation."""

from __future__ import annotations

from .config import Settings
from .db import create_db_pool, close_pool
from .store_base import JobStoreBase
from .store_memory import MemoryJobStore
from .store_postgres import PostgresJobStore
from .time_provider import Clock

__all__ = ["create_store", "close_store"]


async def create_store(settings: Settings, clock: Clock | None = None) -> JobStoreBase:
    """Create a job store (memory or PostgreSQL) based on configuration.
    
    Args:
        settings: Application configuration
        clock: Optional clock for testing (defaults to RealClock)
    
    Returns:
        JobStoreBase implementation (MemoryJobStore if no DATABASE_URL, else PostgresJobStore)
    """
    if settings.database_url:
        pool = await create_db_pool(settings.database_url)
        return PostgresJobStore(
            pool,
            clock=clock,
            reservation_ttl_seconds=settings.reservation_ttl_seconds,
        )
    else:
        return MemoryJobStore(
            clock=clock,
            reservation_ttl_seconds=settings.reservation_ttl_seconds,
        )


async def close_store(store: JobStoreBase) -> None:
    """Close and cleanup the store (closes DB pool if applicable)."""
    if isinstance(store, PostgresJobStore):
        await close_pool()


import uuid


def new_job_id() -> str:
    """Generate a new unique job ID."""
    return f"job_{uuid.uuid4().hex[:12]}"


def new_correlation_id() -> str:
    """Generate a new unique correlation ID."""
    return f"corr_{uuid.uuid4().hex[:12]}"
