"""Certificate inventory + job-result idempotency (Phase 2.6).

Revision ID: 005
Revises: 004
Create Date: 2026-09-05 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bare idempotency marker - the literal "DB-level unique constraint on
    # (job_id, attempt_token)" the plan calls for. record_count is stored
    # here (not recomputed from certificate_records) so a deduped
    # resubmission can report the original recordCount without a second
    # query against the larger table.
    op.create_table(
        "job_results",
        sa.Column("job_id", sa.String(50), nullable=False),
        sa.Column("attempt_token", sa.String(100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("job_id", "attempt_token", name="pk_job_results"),
    )

    op.create_table(
        "certificate_records",
        sa.Column("record_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("job_id", sa.String(50), nullable=False),
        sa.Column("attempt_token", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=True),
        sa.Column("target_id", sa.String(50), nullable=True),
        sa.Column("plugin_id", sa.String(100), nullable=False),
        sa.Column("plugin_version", sa.String(50), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("serial_number", sa.String(200), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(200), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_certificate_records_tenant", "certificate_records", ["tenant_id", "received_at"])
    op.create_index("ix_certificate_records_job", "certificate_records", ["job_id", "attempt_token"])


def downgrade() -> None:
    op.drop_index("ix_certificate_records_job")
    op.drop_index("ix_certificate_records_tenant")
    op.drop_table("certificate_records")
    op.drop_table("job_results")
