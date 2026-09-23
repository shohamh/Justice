"""Add hr_person_syncs and hr_person_sync_errors tables, hr_sync_anomaly_aborted notification type

Revision ID: 20260925_hr_person_sync
Revises: 20260925_hr_hierarchy_node_map
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260925_hr_person_sync"
down_revision = "20260925_hr_hierarchy_node_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_person_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("held_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vanished_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_table(
        "hr_person_sync_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "hr_person_sync_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_person_syncs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("personal_number", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'hr_sync_anomaly_aborted'")


def downgrade() -> None:
    op.drop_table("hr_person_sync_errors")
    op.drop_table("hr_person_syncs")
    # Postgres cannot drop enum values; matches existing repo convention
    # (see b7c8d9e0f1a2_add_qualification_expiry_notification_types.py) of
    # not reversing ALTER TYPE ... ADD VALUE in downgrade.
