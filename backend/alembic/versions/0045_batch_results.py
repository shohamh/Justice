"""add batch_results to algorithm_jobs and batch_index to duty_assignments

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("batch_results", JSONB, nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("batch_index", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("duty_assignments", "batch_index")
    op.drop_column("algorithm_jobs", "batch_results")
