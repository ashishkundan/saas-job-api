"""Gateway heartbeat status (Phase 1.4).

Revision ID: 003
Revises: 002
Create Date: 2026-09-04 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gateway_status",
        sa.Column("gateway_id", sa.String(100), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gateway_version", sa.String(50), nullable=True),
        sa.Column("container_runtime_status", sa.String(20), nullable=True),
        sa.Column("last_successful_job_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_reported_status", sa.String(20), nullable=True),
    )
    op.create_index("ix_gateway_status_last_heartbeat", "gateway_status", ["last_heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_gateway_status_last_heartbeat")
    op.drop_table("gateway_status")
