"""merge ux-improvements into master

Revision ID: e1a591172b65
Revises: 5fe19e1d2a31, ac0f4dcab527
Create Date: 2026-06-17 22:17:35.055412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a591172b65'
down_revision: Union[str, Sequence[str], None] = ('5fe19e1d2a31', 'ac0f4dcab527')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
