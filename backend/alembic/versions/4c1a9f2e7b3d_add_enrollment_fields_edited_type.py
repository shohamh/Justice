"""add enrollment_fields_edited notification type

Revision ID: 4c1a9f2e7b3d
Revises: 990fbafee861
Create Date: 2026-07-27

"""
from alembic import op

revision = "4c1a9f2e7b3d"
down_revision = "990fbafee861"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_fields_edited'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the type.
    pass
