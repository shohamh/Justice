"""add weapon_ineligible_detected notification type

Revision ID: 5abac7d1ec0b
Revises: a1e57979ac8e
Create Date: 2026-08-08 18:40:31.219203

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5abac7d1ec0b'
down_revision: Union[str, Sequence[str], None] = 'a1e57979ac8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'weapon_ineligible_detected'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
