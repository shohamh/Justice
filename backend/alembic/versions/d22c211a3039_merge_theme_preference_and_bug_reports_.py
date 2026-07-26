"""merge theme preference and bug reports heads

Revision ID: d22c211a3039
Revises: 0065, b7e4a19f6c3d
Create Date: 2026-07-25 17:24:49.934318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd22c211a3039'
down_revision: Union[str, Sequence[str], None] = ('0065', 'b7e4a19f6c3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
