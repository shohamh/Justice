"""add range_covers_duty_info notification type

Revision ID: a3f1c9d7e2b4
Revises: 86aec296e732
Create Date: 2026-08-11 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d7e2b4'
down_revision: Union[str, Sequence[str], None] = '86aec296e732'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_covers_duty_info'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
