"""add corps enum level

Revision ID: 0052
Revises: 0051
Create Date: 2026-06-19
"""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE commits outside the transaction automatically in Postgres 12+.
    # The new value is NOT usable in the same transaction — migration 0053 uses it.
    op.execute("ALTER TYPE hierarchy_level ADD VALUE IF NOT EXISTS 'corps' BEFORE 'division'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the type.
    pass
