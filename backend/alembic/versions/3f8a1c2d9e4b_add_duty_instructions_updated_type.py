"""add duty_instructions_updated notification type

Revision ID: 3f8a1c2d9e4b
Revises: 20260901_field_update_dual
"""

from alembic import op


revision = "3f8a1c2d9e4b"
down_revision = "20260901_field_update_dual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'duty_instructions_updated'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
