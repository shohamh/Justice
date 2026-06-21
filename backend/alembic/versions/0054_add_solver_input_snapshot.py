"""add solver_input_snapshot to algorithm_jobs

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("solver_input_snapshot", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("algorithm_jobs", "solver_input_snapshot")
