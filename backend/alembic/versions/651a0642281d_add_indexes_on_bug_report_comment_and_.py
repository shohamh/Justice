"""add indexes on bug report comment and attachment FKs

Revision ID: 651a0642281d
Revises: d18bea0e6cbb
Create Date: 2026-07-31 08:52:15.010061

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '651a0642281d'
down_revision: Union[str, Sequence[str], None] = 'd18bea0e6cbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_bug_report_comments_bug_report_id", "bug_report_comments", ["bug_report_id"]
    )
    op.create_index(
        "ix_bug_report_comment_attachments_comment_id", "bug_report_comment_attachments", ["comment_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_bug_report_comment_attachments_comment_id", table_name="bug_report_comment_attachments")
    op.drop_index("ix_bug_report_comments_bug_report_id", table_name="bug_report_comments")
