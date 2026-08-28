"""add personal_constraint_overridden notification type

Revision ID: 27dc951bcc93
Revises: d4e5f6a7b8c9
Create Date: 2026-08-28 08:58:49.755859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27dc951bcc93'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'personal_constraint_overridden'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
