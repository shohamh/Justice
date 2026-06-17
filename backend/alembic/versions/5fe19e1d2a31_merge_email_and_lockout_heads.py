"""merge_email_and_lockout_heads

Revision ID: 5fe19e1d2a31
Revises: 0050, 1506edfdeb2b
Create Date: 2026-06-17 19:22:54.095175

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fe19e1d2a31'
down_revision: Union[str, Sequence[str], None] = ('0050', '1506edfdeb2b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
