"""add read_at and system_announcement type

Revision ID: 2abd7f54dac6
Revises: d22c211a3039
Create Date: 2026-07-26

"""
from alembic import op
import sqlalchemy as sa

revision = "2abd7f54dac6"
down_revision = "d22c211a3039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'system_announcement'")
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "read_at")
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the type.
