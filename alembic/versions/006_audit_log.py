"""Append-only audit log (Phase 2.7).

Revision ID: 006
Revises: 005
Create Date: 2026-09-05 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_occurred", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_tenant_occurred", "audit_events", ["tenant_id", "occurred_at"])
    # No update/delete-supporting index needed - nothing in this repo ever
    # updates or deletes a row in this table.


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_occurred")
    op.drop_index("ix_audit_events_occurred")
    op.drop_table("audit_events")
