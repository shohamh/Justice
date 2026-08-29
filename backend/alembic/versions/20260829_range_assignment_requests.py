"""add responsible range managers and assignment requests"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829rar1"
down_revision = "20260828aer1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_assignment_request_pending'")
    op.add_column(
        "range_events",
        sa.Column("responsible_duty_manager_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_range_events_responsible_duty_manager",
        "range_events",
        "soldiers",
        ["responsible_duty_manager_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE range_assignment_request_status AS ENUM "
        "('pending', 'approved', 'rejected', 'withdrawn', 'commander_removed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    request_status = postgresql.ENUM(
        "pending", "approved", "rejected", "withdrawn", "commander_removed",
        name="range_assignment_request_status", create_type=False,
    )
    op.create_table(
        "range_assignment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("range_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("system_reason_code", sa.Text(), nullable=True),
        sa.Column("system_reason_text", sa.Text(), nullable=True),
        sa.Column("status", request_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["range_event_id"], ["range_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["soldiers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by"], ["soldiers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_assignment_id"], ["range_assignments.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_range_assignment_requests_event_status",
        "range_assignment_requests",
        ["range_event_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_range_assignment_requests_event_status", table_name="range_assignment_requests")
    op.drop_table("range_assignment_requests")
    postgresql.ENUM(name="range_assignment_request_status").drop(op.get_bind(), checkfirst=True)
    op.drop_constraint("fk_range_events_responsible_duty_manager", "range_events", type_="foreignkey")
    op.drop_column("range_events", "responsible_duty_manager_id")
