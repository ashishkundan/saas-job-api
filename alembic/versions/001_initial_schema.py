"""Initial schema: jobs table with indexes.

Revision ID: 001
Revises: 
Create Date: 2026-08-19 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the jobs table with indexes."""
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("manifest_version", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("state", sa.String(20), nullable=False, server_default="AVAILABLE"),
        sa.Column("correlation_id", sa.String(50), nullable=False),
        sa.Column("trace_id", sa.String(100), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receipt_token", sa.String(100), nullable=True),
        sa.Column("reserved_by", sa.String(100), nullable=True),
        sa.Column("reservation_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ack_gateway_id", sa.String(100), nullable=True),
        sa.Column("ack_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_payload_hash", sa.String(100), nullable=True),
        sa.Column("ack_local_record_version", sa.Integer(), nullable=True),
        sa.Column("acknowledged_receipts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Indexes for query performance
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_state_scheduled", "jobs", ["state", "scheduled_at"])
    op.create_index("ix_jobs_receipt_token", "jobs", ["receipt_token"], unique=True, postgresql_where=sa.text("receipt_token IS NOT NULL"))
    op.create_index("ix_jobs_reserved_until", "jobs", ["reservation_until"], postgresql_where=sa.text("state = 'RESERVED'"))


def downgrade() -> None:
    """Drop the jobs table."""
    op.drop_index("ix_jobs_reserved_until")
    op.drop_index("ix_jobs_receipt_token")
    op.drop_index("ix_jobs_state_scheduled")
    op.drop_index("ix_jobs_state")
    op.drop_table("jobs")
