"""Add rank_last_set_by, review dismissal fields, hr_rank_conflicts table, hr_rank_conflict notification type

Revision ID: 20260927_hr_admin_review
Revises: 20260926_hr_activation_codes
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260927_hr_admin_review"
down_revision = "20260926_hr_activation_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("rank_last_set_by", sa.Text(), nullable=True))
    op.add_column(
        "soldier_hr_profiles",
        sa.Column("review_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "soldier_hr_profiles",
        sa.Column("review_dismissed_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "hr_rank_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "soldier_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("old_rank", sa.Text(), nullable=True),
        sa.Column("new_rank", sa.Text(), nullable=True),
        sa.Column("triggered_by_worker_decision", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("non_sequential_jump", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "hr_person_sync_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_person_syncs.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'hr_rank_conflict'")


def downgrade() -> None:
    op.drop_table("hr_rank_conflicts")
    op.drop_column("soldier_hr_profiles", "review_dismissed_reasons")
    op.drop_column("soldier_hr_profiles", "review_dismissed_at")
    op.drop_column("soldiers", "rank_last_set_by")
    # Postgres cannot drop enum values; matches existing repo convention
    # (20260925_hr_person_sync.py) of not reversing ALTER TYPE ... ADD VALUE.
