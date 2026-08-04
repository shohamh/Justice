"""add reporter_last_seen_at to bug_reports

Revision ID: 5923458a9996
Revises: dd52c6d4e839
Create Date: 2026-08-04 07:34:09.285647

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5923458a9996'
down_revision: Union[str, Sequence[str], None] = 'dd52c6d4e839'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "bug_reports",
        sa.Column("reporter_last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("bug_reports", "reporter_last_seen_at")
