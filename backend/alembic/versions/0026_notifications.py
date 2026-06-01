"""notification system — notifications, telegram_links, notification_preferences, etc.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("type", sa.Enum("swap_offer", "swap_accepted", "swap_rejected", "exemption_approved", "exemption_rejected", "constraint_approved", "constraint_rejected", "assignment_created", "assignment_removed", "score_adjusted", "announcement", name="notification_type", create_type=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("reference_type", sa.Text(), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_notifications_soldier"),
    )

    op.create_table(
        "telegram_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("verification_code", sa.Text(), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notifications_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_telegram_links_soldier"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.Enum("swap_offer", "swap_accepted", "swap_rejected", "exemption_approved", "exemption_rejected", "constraint_approved", "constraint_rejected", "assignment_created", "assignment_removed", "score_adjusted", "announcement", name="notification_type", create_type=False), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_notification_preferences_soldier"),
        sa.UniqueConstraint("soldier_id", "notification_type", name="uq_notification_preferences_soldier_type"),
    )

    op.create_table(
        "commander_notification_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("commander_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["commander_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_cns_commander"),
        sa.ForeignKeyConstraint(["hierarchy_node_id"], ["hierarchy_nodes.id"], ondelete="CASCADE", name="fk_cns_hierarchy_node"),
    )

    op.create_table(
        "telegram_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("telegram_outbox")
    op.drop_table("commander_notification_scopes")
    op.drop_table("notification_preferences")
    op.drop_table("telegram_links")
    op.drop_table("notifications")
    op.execute("DROP TYPE IF EXISTS notification_type")
