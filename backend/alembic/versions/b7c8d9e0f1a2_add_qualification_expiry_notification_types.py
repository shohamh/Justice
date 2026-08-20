"""add qualification expiry notification types

Revision ID: b7c8d9e0f1a2
Revises: c7e8f9a0b1c2
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'c7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'mitvahim_expiring_soon'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'mitvahim_expired'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'alal_expiring_soon'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'alal_expired'")


def downgrade() -> None:
    # Postgres cannot drop enum values; matches the existing repo convention
    # (see db05bb8f7744_add_rank_advancement.py) of not reversing
    # ALTER TYPE ... ADD VALUE in downgrade.
    pass
