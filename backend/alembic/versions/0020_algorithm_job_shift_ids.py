"""replace duty_type_ids/duty_location_id with shift_ids on algorithm_jobs

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("shift_ids", postgresql.JSONB(), nullable=True),
    )
    op.execute("UPDATE algorithm_jobs SET shift_ids = '[]' WHERE shift_ids IS NULL")
    op.alter_column("algorithm_jobs", "shift_ids", nullable=False)

    op.drop_column("algorithm_jobs", "duty_type_ids")
    op.drop_column("algorithm_jobs", "duty_location_id")


def downgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("duty_type_ids", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "algorithm_jobs",
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.drop_column("algorithm_jobs", "shift_ids")
