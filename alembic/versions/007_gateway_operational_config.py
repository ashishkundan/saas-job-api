"""Per-Gateway non-secret operational settings.

Revision ID: 007
Revises: 006
Create Date: 2026-10-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gateway_operational_configs",
        sa.Column("gateway_id", sa.String(100), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("poll_interval_ms", sa.Integer(), nullable=False),
        sa.Column("heartbeat_interval_ms", sa.Integer(), nullable=False),
        sa.Column("accept_new_jobs", sa.Boolean(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gateway_operational_configs_tenant", "gateway_operational_configs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_gateway_operational_configs_tenant")
    op.drop_table("gateway_operational_configs")
