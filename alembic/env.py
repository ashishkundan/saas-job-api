"""Alembic environment script for async database migrations."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (script-only, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Run migrations against the database connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def _async_sqlalchemy_url(database_url: str | None) -> str:
    """Normalize a plain postgresql:// URL (e.g. Render's connection string,
    or asyncpg's own DSN format used by db.py) into the asyncpg SQLAlchemy
    dialect create_async_engine requires. Without this, a plain postgresql://
    URL makes SQLAlchemy pick the sync psycopg2 driver (not installed) and
    migrations fail immediately - this was previously untested against the
    real connection string format used in production."""
    if database_url is None:
        return "sqlite+aiosqlite:///:memory:"
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://"):]
    if database_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + database_url[len("postgres://"):]
    return database_url


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with live DB connection)."""
    from saas_job_api.config import settings

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = _async_sqlalchemy_url(settings.database_url)

    connectable = create_async_engine(
        configuration["sqlalchemy.url"],
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
