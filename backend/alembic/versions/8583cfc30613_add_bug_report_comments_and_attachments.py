"""add bug report comments and attachments

Revision ID: 8583cfc30613
Revises: c4644d9c8590
Create Date: 2026-07-30 19:50:29.408992

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8583cfc30613'
down_revision: Union[str, Sequence[str], None] = 'c4644d9c8590'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "bug_report_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("bug_report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bug_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "bug_report_comment_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("comment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bug_report_comments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("bug_report_comment_attachments")
    op.drop_table("bug_report_comments")
