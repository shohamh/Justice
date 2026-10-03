"""merge scale and current dev migration heads

Revision ID: 07027d6dd2dd
Revises: 20261002_cursor_revision_deps, 366e272a0dae
Create Date: 2026-10-03 22:01:21.435842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07027d6dd2dd'
down_revision: Union[str, Sequence[str], None] = ('20261002_cursor_revision_deps', '366e272a0dae')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
