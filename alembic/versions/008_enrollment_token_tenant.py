"""Bind Gateway enrollment tokens to an optional tenant.

Revision ID: 008
Revises: 007
Create Date: 2026-10-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("enrollment_tokens", sa.Column("tenant_id", sa.String(50), nullable=True))
    op.create_foreign_key(
        "fk_enrollment_tokens_tenant_id_tenants",
        "enrollment_tokens",
        "tenants",
        ["tenant_id"],
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_enrollment_tokens_tenant_id_tenants", "enrollment_tokens", type_="foreignkey")
    op.drop_column("enrollment_tokens", "tenant_id")
