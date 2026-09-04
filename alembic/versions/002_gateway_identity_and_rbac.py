"""Gateway identity (mTLS registration) and RBAC (admin principals).

Revision ID: 002
Revises: 001
Create Date: 2026-09-04 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enrollment_tokens",
        sa.Column("token_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by", sa.String(50), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_gateway_id", sa.String(100), nullable=True),
    )
    op.create_index("ix_enrollment_tokens_hash", "enrollment_tokens", ["token_hash"], unique=True)

    op.create_table(
        "gateway_identities",
        sa.Column("gateway_id", sa.String(100), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=True),
        sa.Column("public_key_fingerprint", sa.String(128), nullable=False),
        sa.Column("certificate_pem", sa.Text(), nullable=False),
        sa.Column("certificate_serial", sa.String(64), nullable=False),
        sa.Column("certificate_not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "admin_principals",
        sa.Column("principal_id", sa.String(50), nullable=False, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_principals_username", "admin_principals", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_admin_principals_username")
    op.drop_table("admin_principals")
    op.drop_table("gateway_identities")
    op.drop_index("ix_enrollment_tokens_hash")
    op.drop_table("enrollment_tokens")
