"""Add enrollment notification types to notification_type enum

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-03

"""
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_request_received'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_approved'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_rejected'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
