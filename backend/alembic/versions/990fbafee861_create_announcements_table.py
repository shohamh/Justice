"""create announcements table

Revision ID: 990fbafee861
Revises: 2abd7f54dac6
Create Date: 2026-07-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "990fbafee861"
down_revision = "2abd7f54dac6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("type", postgresql.ENUM("announcement", "system_announcement", name="notification_type", create_type=False), nullable=False),
        sa.Column("hierarchy_node_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_announcements_sender_id", "announcements", ["sender_id"])


def downgrade() -> None:
    op.drop_index("ix_announcements_sender_id", table_name="announcements")
    op.drop_table("announcements")
