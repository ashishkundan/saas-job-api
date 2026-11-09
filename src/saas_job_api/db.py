"""PostgreSQL connection pool and database utilities."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from asyncpg import Pool, create_pool

__all__ = ["create_db_pool", "get_pool", "sqlalchemy_async_url"]


def sqlalchemy_async_url(database_url: str) -> str:
    """The asyncpg SQLAlchemy URL Alembic needs for SAAS_JOB_API_DATABASE_URL.

    The setting is an asyncpg/libpq-style DSN (Render's connection string,
    or Azure's ``...?sslmode=require``). A plain postgresql:// URL would make
    SQLAlchemy pick the sync psycopg2 driver (not installed), and SQLAlchemy's
    asyncpg dialect rejects libpq's ``sslmode`` - it takes ``ssl`` instead."""
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            database_url = "postgresql+asyncpg://" + database_url[len(prefix):]
            break
    parts = urlsplit(database_url)
    query = [("ssl" if key == "sslmode" else key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(query)))

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
