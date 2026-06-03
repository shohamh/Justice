"""add progress_message to algorithm_jobs

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("algorithm_jobs", sa.Column("progress_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("algorithm_jobs", "progress_message")
