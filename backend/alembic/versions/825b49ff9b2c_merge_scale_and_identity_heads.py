"""merge scale and identity heads

Revision ID: 825b49ff9b2c
Revises: 07027d6dd2dd, fe129be97333
Create Date: 2026-10-04 00:05:11.655634

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '825b49ff9b2c'
down_revision: Union[str, Sequence[str], None] = ('07027d6dd2dd', 'fe129be97333')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
