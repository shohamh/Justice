"""add auto_roll_until to shift_templates

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shift_templates",
        sa.Column("auto_roll_until", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shift_templates", "auto_roll_until")
