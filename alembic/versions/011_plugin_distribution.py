"""Plugin distribution: signed repository files and per-tenant entitlements.

plugin_repo_files holds the TUF repository the SaaS serves to gateways
(untrusted transport - gateways verify every byte). tenant_plugins records
which plugins each tenant may use; it is seeded from the plugins existing
targets already use, so nothing that works today stops working.

Revision ID: 011
Revises: 010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_repo_files",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("path", sa.String(300), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tenant_plugins",
        sa.Column("tenant_id", sa.String(50), primary_key=True),
        sa.Column("plugin_ref", sa.String(100), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "INSERT INTO tenant_plugins (tenant_id, plugin_ref, created_at) "
        "SELECT DISTINCT tenant_id, plugin_ref, now() FROM targets "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("tenant_plugins")
    op.drop_table("plugin_repo_files")
