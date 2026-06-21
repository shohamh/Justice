"""add start_time/end_time to duty_shifts

Revision ID: 0055
Revises: 0054
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_shifts",
        sa.Column("start_time", sa.Text(), nullable=False, server_default="00:00"),
    )
    op.add_column(
        "duty_shifts",
        sa.Column("end_time", sa.Text(), nullable=False, server_default="23:59"),
    )


def downgrade() -> None:
    op.drop_column("duty_shifts", "end_time")
    op.drop_column("duty_shifts", "start_time")
