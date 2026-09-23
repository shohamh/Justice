"""Add soldier_activation_codes table and hr_onboarding_completed_at

Revision ID: 20260926_hr_activation_codes
Revises: 20260925_hr_person_sync
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260926_hr_activation_codes"
down_revision = "20260925_hr_person_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "soldiers", sa.Column("hr_onboarding_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "soldier_activation_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "soldier_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("soldier_activation_codes")
    op.drop_column("soldiers", "hr_onboarding_completed_at")
