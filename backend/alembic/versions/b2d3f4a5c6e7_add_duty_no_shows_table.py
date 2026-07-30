"""Add duty_no_shows table and no_show_marked notification type

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3f4b5d6
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2d3f4a5c6e7"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'no_show_marked'")
    op.create_table(
        "duty_no_shows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("score_adjustment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_duty_no_shows_assignment", "duty_no_shows", ["duty_assignment_id"])


def downgrade() -> None:
    op.drop_table("duty_no_shows")
    # Postgres cannot drop a single enum value; no-op on downgrade for notification_type.
