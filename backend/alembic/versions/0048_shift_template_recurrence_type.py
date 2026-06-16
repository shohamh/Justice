"""add recurrence_type to shift_templates

Revision ID: 0048
Revises: 0047
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shift_templates",
        sa.Column(
            "recurrence_type",
            sa.Text(),
            nullable=False,
            server_default="weekly",
        ),
    )
    op.create_check_constraint(
        "ck_shift_templates_recurrence_type",
        "shift_templates",
        "recurrence_type IN ('daily', 'weekdays', 'weekly')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_shift_templates_recurrence_type", "shift_templates", type_="check")
    op.drop_column("shift_templates", "recurrence_type")
