"""Add operational fields to duty_types

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("duty_types", sa.Column("contact_name", sa.Text, nullable=True))
    op.add_column("duty_types", sa.Column("contact_phone", sa.Text, nullable=True))
    op.add_column("duty_types", sa.Column("start_time", sa.Time, nullable=True))
    op.add_column("duty_types", sa.Column("end_time", sa.Time, nullable=True))
    op.add_column("duty_types", sa.Column("instructions", sa.Text, nullable=True))
    op.add_column(
        "duty_types",
        sa.Column("is_external", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.alter_column("duty_types", "is_external", server_default=None)


def downgrade() -> None:
    op.drop_column("duty_types", "is_external")
    op.drop_column("duty_types", "instructions")
    op.drop_column("duty_types", "end_time")
    op.drop_column("duty_types", "start_time")
    op.drop_column("duty_types", "contact_phone")
    op.drop_column("duty_types", "contact_name")
