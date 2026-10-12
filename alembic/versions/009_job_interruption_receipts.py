"""Deduplicate accepted interrupted-attempt notifications.

Revision ID: 009
Revises: 008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_interruption_receipts",
        sa.Column("job_id", sa.String(50), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("gateway_id", sa.String(100), primary_key=True),
        sa.Column("attempt_token", sa.Text(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_interruption_receipts")
