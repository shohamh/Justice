"""Add bug_reports table

Revision ID: b7e4a19f6c3d
Revises: 71e217f7c372
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b7e4a19f6c3d"
down_revision = "71e217f7c372"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE bug_report_severity AS ENUM ('low', 'medium', 'high')")
    op.execute("CREATE TYPE bug_report_status AS ENUM ('open', 'in_progress', 'resolved')")
    op.create_table(
        "bug_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", postgresql.ENUM("low", "medium", "high", name="bug_report_severity", create_type=False), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("status", postgresql.ENUM("open", "in_progress", "resolved", name="bug_report_status", create_type=False), server_default="open", nullable=False),
        sa.Column("screenshot", sa.LargeBinary(), nullable=True),
        sa.Column("nav_history", postgresql.JSONB(), nullable=True),
        sa.Column("audit_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("user_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("json_file_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bug_reports")
    op.execute("DROP TYPE bug_report_severity")
    op.execute("DROP TYPE bug_report_status")
