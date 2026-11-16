"""Index for the scheduler's overlap guard.

Before a schedule fires, the scheduler looks for that schedule's previous
job still open on the same target. A partial index on unfinished jobs keeps
that lookup small no matter how many completed jobs accumulate.

Revision ID: 013
Revises: 012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_open_by_target",
        "jobs",
        ["tenant_id", "target_id"],
        postgresql_where=sa.text("state <> 'COMPLETED'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_open_by_target", table_name="jobs")
