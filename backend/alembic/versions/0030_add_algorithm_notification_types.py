"""add algorithm_job_done and algorithm_job_failed notification types

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-02

"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'algorithm_job_done'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'algorithm_job_failed'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
