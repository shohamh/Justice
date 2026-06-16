"""add duration_days to shift_templates

Revision ID: 0049
Revises: 0048
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shift_templates",
        sa.Column(
            "duration_days",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("shift_templates", "duration_days")
