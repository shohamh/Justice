"""add result_metadata to algorithm_jobs

Revision ID: 0046
Revises: 0045
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("result_metadata", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("algorithm_jobs", "result_metadata")
