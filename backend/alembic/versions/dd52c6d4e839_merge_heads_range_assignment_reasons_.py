"""merge heads: range assignment reasons + bug report comment notification

Revision ID: dd52c6d4e839
Revises: 20260803rar1, f7a8b9c0d1e2
Create Date: 2026-08-04 00:12:46.372687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd52c6d4e839'
down_revision: Union[str, Sequence[str], None] = ('20260803rar1', 'f7a8b9c0d1e2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
