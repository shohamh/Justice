"""merge exemption-cancellation and linked-commander-exemption heads

Revision ID: 3dd30881eefd
Revises: 1a5c77b91db5, b2c3d4e5f6a1
Create Date: 2026-07-07 20:13:11.668612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3dd30881eefd'
down_revision: Union[str, Sequence[str], None] = ('1a5c77b91db5', 'b2c3d4e5f6a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
