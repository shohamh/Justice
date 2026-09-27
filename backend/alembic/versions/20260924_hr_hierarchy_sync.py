"""Add hr_hierarchy_syncs table

Revision ID: 20260924_hr_hierarchy_sync
Revises: 20260923_soldier_hr_profile
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_hr_hierarchy_sync"
down_revision = "20260923_soldier_hr_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_hierarchy_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_state", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("held_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("hr_hierarchy_syncs")
