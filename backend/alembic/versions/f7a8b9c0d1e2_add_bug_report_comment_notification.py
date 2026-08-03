"""add bug report comment notification type

Revision ID: f7a8b9c0d1e2
Revises: 20260802rq01
"""

from alembic import op


revision = "f7a8b9c0d1e2"
down_revision = "20260802rq01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'bug_report_comment'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
