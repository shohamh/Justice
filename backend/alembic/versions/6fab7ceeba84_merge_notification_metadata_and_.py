"""merge notification metadata and transparency settings heads

Revision ID: 6fab7ceeba84
Revises: 0e39f17b207b, e5ed06d0a69b
Create Date: 2026-08-10 13:01:07.982293

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fab7ceeba84'
down_revision: Union[str, Sequence[str], None] = ('0e39f17b207b', 'e5ed06d0a69b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
