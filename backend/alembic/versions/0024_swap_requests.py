"""swap_requests table

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "swap_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("duty_date", sa.Date(), nullable=False),
        sa.Column("requesting_soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_soldier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("covering_soldier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requester_side_approved", sa.Boolean(), nullable=True),
        sa.Column("covering_side_approved", sa.Boolean(), nullable=True),
        sa.Column("resulting_override_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["duty_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_swap_requests_duty_assignment_id"),
        sa.ForeignKeyConstraint(["requesting_soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_swap_requests_requesting_soldier_id"),
        sa.ForeignKeyConstraint(["target_soldier_id"], ["soldiers.id"], ondelete="SET NULL", name="fk_swap_requests_target_soldier_id"),
        sa.ForeignKeyConstraint(["covering_soldier_id"], ["soldiers.id"], ondelete="SET NULL", name="fk_swap_requests_covering_soldier_id"),
        sa.ForeignKeyConstraint(["resulting_override_id"], ["duty_day_overrides.id"], ondelete="SET NULL", name="fk_swap_requests_resulting_override_id"),
    )
    op.create_index("ix_swap_requests_status", "swap_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_swap_requests_status", table_name="swap_requests")
    op.drop_table("swap_requests")
