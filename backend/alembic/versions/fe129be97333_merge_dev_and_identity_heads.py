"""merge dev and identity heads

Revision ID: fe129be97333
Revises: 20261003_merge_identity_heads, 366e272a0dae
Create Date: 2026-10-03 23:27:04.246638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe129be97333'
down_revision: Union[str, Sequence[str], None] = ('20261003_merge_identity_heads', '366e272a0dae')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
