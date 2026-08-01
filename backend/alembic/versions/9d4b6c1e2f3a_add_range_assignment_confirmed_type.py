"""add range_assignment_confirmed notification type

Revision ID: 9d4b6c1e2f3a
Revises: 7a13f6c9b8e2
Create Date: 2026-08-01

"""
from alembic import op

revision = "9d4b6c1e2f3a"
down_revision = "7a13f6c9b8e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_assignment_confirmed'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the type.
    pass
