"""PostgreSQL connection pool and database utilities."""

from __future__ import annotations

from asyncpg import Pool, create_pool

__all__ = ["create_db_pool", "get_pool"]

_pool: Pool | None = None


async def create_db_pool(database_url: str, min_size: int = 10, max_size: int = 20) -> Pool:
    """Create and return an asyncpg connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()

    _pool = await create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=60,
        max_cached_statement_lifetime=300,
        max_cacheable_statement_size=15000,
    )
    return _pool


def get_pool() -> Pool | None:
    """Get the current connection pool (or None if not initialized)."""
    return _pool


async def close_pool() -> None:
    """Close and cleanup the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
