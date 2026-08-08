"""merge_range_attendance_correction_and_weapon_qualification_heads

Revision ID: 55bf8c15f4b3
Revises: 7199fa0e2b23, fa5a2130f396
Create Date: 2026-08-08 07:52:18.809134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55bf8c15f4b3'
down_revision: Union[str, Sequence[str], None] = ('7199fa0e2b23', 'fa5a2130f396')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
