"""add division and unit to hierarchy_level enum

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-30
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE hierarchy_level ADD VALUE IF NOT EXISTS 'division'")
    op.execute("ALTER TYPE hierarchy_level ADD VALUE IF NOT EXISTS 'unit'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum.
    # Downgrade would require creating a new type, migrating, and dropping.
    # This is a no-op — production rollback would be handled by restoring from backup.
    pass
