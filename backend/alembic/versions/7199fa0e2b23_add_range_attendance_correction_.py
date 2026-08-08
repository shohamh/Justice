"""add range attendance correction notification types

Revision ID: 7199fa0e2b23
Revises: 6660cfc999b7
"""

from alembic import op


revision = "7199fa0e2b23"
down_revision = "6660cfc999b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_absence_reported_to_commander'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_attendance_corrected_to_present'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
