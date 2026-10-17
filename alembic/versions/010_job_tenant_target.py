"""Tenant ownership for jobs: jobs.tenant_id / jobs.target_id.

A gateway may only claim jobs belonging to its own tenant (customer), so
the claim query filters on a real column rather than free-form payload
JSON. Existing rows are backfilled from payload tenantId/targetId where
present; rows without a tenantId stay NULL and are never claimable.

Revision ID: 010
Revises: 009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("tenant_id", sa.String(50), nullable=True))
    op.add_column("jobs", sa.Column("target_id", sa.String(50), nullable=True))
    op.execute(
        "UPDATE jobs SET tenant_id = NULLIF(payload->>'tenantId', ''), "
        "target_id = NULLIF(payload->>'targetId', '')"
    )
    op.create_index(
        "ix_jobs_tenant_claim",
        "jobs",
        ["tenant_id", "state", "priority", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_tenant_claim", table_name="jobs")
    op.drop_column("jobs", "target_id")
    op.drop_column("jobs", "tenant_id")
