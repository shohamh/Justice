"""Add soldier_hr_profiles table

Revision ID: 20260923_soldier_hr_profile
Revises: f43bbf6cc6ed
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260923_soldier_hr_profile"
down_revision = "f43bbf6cc6ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soldier_hr_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("personal_number", sa.Text(), nullable=False, unique=True),
        sa.Column("raw_dto", postgresql.JSONB(), nullable=False),
        sa.Column(
            "soldier_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, unique=True,
        ),
        sa.Column("sync_status", sa.Text(), server_default="held_for_review", nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("overridden_fields", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("soldier_hr_profiles")
