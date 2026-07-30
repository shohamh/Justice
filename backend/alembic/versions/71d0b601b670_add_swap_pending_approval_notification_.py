"""add swap_pending_approval notification type

Revision ID: 71d0b601b670
Revises: 6b45caf468c2
Create Date: 2026-07-30 14:56:37.093041

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71d0b601b670'
down_revision: Union[str, Sequence[str], None] = '6b45caf468c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'swap_pending_approval'")


def downgrade() -> None:
    """Downgrade schema."""
    pass  # Postgres doesn't support removing enum values; downgrade is a no-op.
