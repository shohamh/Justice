"""add status to duty_shifts

Revision ID: 0047
Revises: 0046
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_shifts",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )


def downgrade() -> None:
    op.drop_column("duty_shifts", "status")
