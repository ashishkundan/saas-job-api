"""Database URL handling for Alembic (Render and Azure connection strings)
and the per-replica connection pool size."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from saas_job_api.config import Settings
from saas_job_api.db import sqlalchemy_async_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgres://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        # Azure Flexible Server requires TLS; SQLAlchemy's asyncpg dialect takes ssl, not sslmode.
        ("postgresql://u:p@psql-cv360-dev.postgres.database.azure.com:5432/saas?sslmode=require",
         "postgresql+asyncpg://u:p@psql-cv360-dev.postgres.database.azure.com:5432/saas?ssl=require"),
        ("postgresql+asyncpg://u:p@host/db?ssl=require", "postgresql+asyncpg://u:p@host/db?ssl=require"),
    ],
)
def test_sqlalchemy_async_url(url: str, expected: str) -> None:
    assert sqlalchemy_async_url(url) == expected


def test_password_characters_are_left_alone() -> None:
    url = "postgresql://cvadmin:p%40ss%2Fw0rd@host/db?sslmode=require&application_name=saas"
    assert sqlalchemy_async_url(url) == (
        "postgresql+asyncpg://cvadmin:p%40ss%2Fw0rd@host/db?ssl=require&application_name=saas"
    )


def test_pool_size_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("SAAS_JOB_API_DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("SAAS_JOB_API_DB_POOL_MAX_SIZE", "8")
    settings = Settings()
    assert (settings.db_pool_min_size, settings.db_pool_max_size) == (2, 8)


def test_pool_size_bounds(monkeypatch) -> None:
    monkeypatch.setenv("SAAS_JOB_API_DB_POOL_MAX_SIZE", "0")
    with pytest.raises(ValidationError):
        Settings()
