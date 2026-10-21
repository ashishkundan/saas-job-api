"""Per-tenant plugin version pinning.

tenant_plugins.pinned_version is the version of a plugin a tenant runs by
default; targets.plugin_version becomes an optional per-target override
(NULL = follow the tenant's pin). Existing targets keep their explicit
version, so nothing changes until a pin is set and overrides are cleared.

Revision ID: 012
Revises: 011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_plugins", sa.Column("pinned_version", sa.String(64), nullable=True))
    # Also widen to the gateway's version length (64).
    op.alter_column("targets", "plugin_version", existing_type=sa.String(50), type_=sa.String(64), nullable=True)


def downgrade() -> None:
    # Targets that followed a pin get it written back before NOT NULL returns.
    op.execute(
        "UPDATE targets t SET plugin_version = p.pinned_version FROM tenant_plugins p "
        "WHERE t.plugin_version IS NULL AND p.tenant_id = t.tenant_id AND p.plugin_ref = t.plugin_ref"
    )
    op.alter_column("targets", "plugin_version", existing_type=sa.String(64), type_=sa.String(50), nullable=False)
    op.drop_column("tenant_plugins", "pinned_version")
