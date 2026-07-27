"""merge unify-swap-requests and enrollment-fields-edited-type heads

Revision ID: 63cff804e3e4
Revises: 4a4997526f58, 4c1a9f2e7b3d
Create Date: 2026-07-27 23:02:41.293102

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63cff804e3e4'
down_revision: Union[str, Sequence[str], None] = ('4a4997526f58', '4c1a9f2e7b3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
