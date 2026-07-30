"""add wont_fix to bug_report_status

Revision ID: c4644d9c8590
Revises: 71d0b601b670
Create Date: 2026-07-30 19:43:25.983806

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4644d9c8590'
down_revision: Union[str, Sequence[str], None] = '71d0b601b670'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE bug_report_status ADD VALUE IF NOT EXISTS 'wont_fix'")


def downgrade() -> None:
    """Downgrade schema."""
    pass  # Postgres doesn't support removing enum values; downgrade is a no-op.
