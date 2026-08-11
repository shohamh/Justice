"""add_duty_assignment_range_info_cache

Revision ID: 86aec296e732
Revises: 6fab7ceeba84
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '86aec296e732'
down_revision: Union[str, Sequence[str], None] = '6fab7ceeba84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_covered_by_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_covering_range_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_duty_assignments_range_info_active",
        "duty_assignments",
        ["id"],
        unique=False,
        postgresql_where=sa.text("range_info_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_duty_assignments_range_info_active", table_name="duty_assignments")
    op.drop_column("duty_assignments", "range_info_detected_at")
    op.drop_column("duty_assignments", "range_info_covering_range_type")
    op.drop_column("duty_assignments", "range_info_covered_by_date")
    op.drop_column("duty_assignments", "range_info_active")
