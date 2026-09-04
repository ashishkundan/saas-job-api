"""Tenant / Target / Schedule resources + tenant-scoped RBAC (Phase 2.5).

Revision ID: 004
Revises: 003
Create Date: 2026-09-04 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("admin_principals", sa.Column("tenant_id", sa.String(50), nullable=True))

    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "targets",
        sa.Column("target_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("plugin_ref", sa.String(100), nullable=False),
        sa.Column("plugin_version", sa.String(50), nullable=False),
        sa.Column("credential_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_targets_tenant", "targets", ["tenant_id"])

    op.create_table(
        "schedules",
        sa.Column("schedule_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(50), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("manifest_version", sa.String(50), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_schedules_tenant", "schedules", ["tenant_id"])
    # The exact index scheduler_tick.py's claim query needs: enabled +
    # next_run_at is the WHERE clause of the SKIP LOCKED SELECT.
    op.create_index("ix_schedules_due", "schedules", ["enabled", "next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_schedules_due")
    op.drop_index("ix_schedules_tenant")
    op.drop_table("schedules")
    op.drop_index("ix_targets_tenant")
    op.drop_table("targets")
    op.drop_table("tenants")
    op.drop_column("admin_principals", "tenant_id")
