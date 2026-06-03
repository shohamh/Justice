"""telegram actionable notifications: new types, action tokens, commander depth

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New notification types
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'constraint_pending'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'exemption_request_pending'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'swap_offer_incoming'")

    # reply_markup_json on telegram_outbox
    op.add_column("telegram_outbox", sa.Column("reply_markup_json", sa.Text(), nullable=True))

    # One-time action tokens
    op.create_table(
        "telegram_action_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extra_json", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awaiting_text_from_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE",
                                name="fk_action_tokens_soldier"),
    )
    op.create_index("ix_action_tokens_token", "telegram_action_tokens", ["token"], unique=True)
    op.create_index("ix_action_tokens_await_chat", "telegram_action_tokens", ["awaiting_text_from_chat_id"])

    # Commander notification depth preferences
    op.create_table(
        "commander_notification_depth",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("commander_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", postgresql.ENUM(
            "swap_offer", "swap_accepted", "swap_rejected",
            "exemption_approved", "exemption_rejected",
            "constraint_approved", "constraint_rejected",
            "assignment_created", "assignment_removed",
            "score_adjusted", "announcement",
            "algorithm_job_done", "algorithm_job_failed",
            "constraint_pending", "exemption_request_pending", "swap_offer_incoming",
            name="notification_type", create_type=False,
        ), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["commander_id"], ["soldiers.id"], ondelete="CASCADE",
                                name="fk_cmd_depth_soldier"),
        sa.UniqueConstraint("commander_id", "notification_type", name="uq_cmd_depth_soldier_type"),
    )


def downgrade() -> None:
    op.drop_table("commander_notification_depth")
    op.drop_index("ix_action_tokens_await_chat", table_name="telegram_action_tokens")
    op.drop_index("ix_action_tokens_token", table_name="telegram_action_tokens")
    op.drop_table("telegram_action_tokens")
    op.drop_column("telegram_outbox", "reply_markup_json")
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for new types.
