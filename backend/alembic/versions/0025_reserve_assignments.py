"""reserve assignments — duty_dismissals, duty_reserve_links, new columns

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("duty_types", sa.Column("reserve_ratio", sa.Numeric(4, 3), server_default=sa.text("0.000"), nullable=False))
    op.add_column("duty_types", sa.Column("reserve_minimum", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("duty_shifts", sa.Column("reserve_count_override", sa.Integer(), nullable=True))
    op.add_column("duty_assignments", sa.Column("is_reserve", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("duty_assignments", sa.Column("called_up_from", sa.Date(), nullable=True))
    op.add_column("duty_assignments", sa.Column("called_up_to", sa.Date(), nullable=True))

    op.create_table(
        "duty_dismissals",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dismissed_from", sa.Date(), nullable=False),
        sa.Column("dismissed_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["duty_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_duty_dismissals_assignment"),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_duty_dismissals_created_by"),
    )

    op.create_table(
        "duty_reserve_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("reserve_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_distance", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["reserve_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_reserve_links_reserve"),
        sa.ForeignKeyConstraint(["primary_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_reserve_links_primary"),
        sa.UniqueConstraint("primary_assignment_id", name="uq_reserve_links_primary"),
    )

    op.drop_table("reserve_assignments")


def downgrade() -> None:
    op.create_table(
        "reserve_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reserve_soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.drop_table("duty_reserve_links")
    op.drop_table("duty_dismissals")
    op.drop_column("duty_assignments", "called_up_to")
    op.drop_column("duty_assignments", "called_up_from")
    op.drop_column("duty_assignments", "is_reserve")
    op.drop_column("duty_shifts", "reserve_count_override")
    op.drop_column("duty_types", "reserve_minimum")
    op.drop_column("duty_types", "reserve_ratio")
