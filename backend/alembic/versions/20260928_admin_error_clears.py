"""Create per-admin soft-clear cursors for the admin error inbox.

Replaces the old hard delete of error log lines (from local log files) with a
per-admin "cleared before" timestamp, now that error logs live in Loki.

Revision ID: 20260928_admin_error_clears
Revises: 20260927_hr_admin_review
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260928_admin_error_clears"
down_revision = "20260927_hr_admin_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_error_clears",
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cleared_before", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_error_clears")
