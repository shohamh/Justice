"""Persist Exchange mirror state, jobs, attempt history, and worker state.

Revision ID: 20260928_exchange_outbox
Revises: 20260928_admin_error_clears
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260928_exchange_outbox"
down_revision = "20260928_admin_error_clears"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_calendar_sync_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("exchange_item_id", sa.Text(), nullable=True),
        sa.Column("exchange_change_key", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_error_category", sa.Text(), nullable=True),
        sa.Column("current_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("source_type", "source_id", name="uq_exchange_calendar_sync_source"),
        sa.CheckConstraint(
            "source_type IN ('duty_shift', 'duty_assignment', 'range_event')",
            name="ck_exchange_calendar_sync_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'in_progress', 'synced', 'partial', 'retry_wait', 'failed', 'cancelled')",
            name="ck_exchange_calendar_sync_status",
        ),
    )
    op.create_index("ix_exchange_calendar_sync_status", "exchange_calendar_sync_items", ["status"])
    op.create_index(
        "ix_exchange_calendar_sync_source_date", "exchange_calendar_sync_items", ["source_date"]
    )

    op.create_table(
        "exchange_calendar_outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('duty_shift', 'duty_assignment', 'range_event')",
            name="ck_exchange_calendar_outbox_source_type",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_exchange_calendar_outbox_priority"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_exchange_calendar_outbox_attempts"),
        sa.CheckConstraint(
            "status IN ('queued', 'leased', 'completed', 'failed', 'cancelled')",
            name="ck_exchange_calendar_outbox_status",
        ),
    )
    # Coalesce queued work per source while allowing one leased row and one
    # queued follow-up to coexist after a mutation races the worker snapshot.
    op.create_index(
        "uq_exchange_calendar_outbox_pending_source",
        "exchange_calendar_outbox",
        ["source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_exchange_calendar_outbox_due",
        "exchange_calendar_outbox",
        ["status", "next_attempt_at", sa.text("priority DESC"), "queued_at"],
    )
    op.create_index(
        "ix_exchange_calendar_outbox_lease",
        "exchange_calendar_outbox",
        ["status", "lease_expires_at"],
    )

    op.create_table(
        "exchange_calendar_sync_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("sync_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_category", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sync_item_id"],
            ["exchange_calendar_sync_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["exchange_calendar_outbox.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "outcome IN ('created', 'updated', 'cancelled', 'unchanged', 'partial', 'failed', 'skipped')",
            name="ck_exchange_calendar_attempt_outcome",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_exchange_calendar_attempt_duration",
        ),
    )
    op.create_index(
        "ix_exchange_calendar_attempt_history",
        "exchange_calendar_sync_attempts",
        ["sync_item_id", "attempted_at"],
    )

    op.create_table(
        "exchange_calendar_worker_state",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exchange_reachable", sa.Boolean(), nullable=True),
        sa.Column("last_connection_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_connection_error", sa.Text(), nullable=True),
        sa.Column("global_backoff_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_exchange_calendar_worker_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("exchange_calendar_worker_state")
    op.drop_index(
        "ix_exchange_calendar_attempt_history", table_name="exchange_calendar_sync_attempts"
    )
    op.drop_table("exchange_calendar_sync_attempts")
    op.drop_index("ix_exchange_calendar_outbox_lease", table_name="exchange_calendar_outbox")
    op.drop_index("ix_exchange_calendar_outbox_due", table_name="exchange_calendar_outbox")
    op.drop_index(
        "uq_exchange_calendar_outbox_pending_source", table_name="exchange_calendar_outbox"
    )
    op.drop_table("exchange_calendar_outbox")
    op.drop_index(
        "ix_exchange_calendar_sync_source_date", table_name="exchange_calendar_sync_items"
    )
    op.drop_index("ix_exchange_calendar_sync_status", table_name="exchange_calendar_sync_items")
    op.drop_table("exchange_calendar_sync_items")
