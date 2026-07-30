"""merge heads: bug-report-comments batch + personal-constraint-default

Revision ID: d18bea0e6cbb
Revises: 8583cfc30613, c3e4f5a6b7d8
Create Date: 2026-07-31 00:41:39.177678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd18bea0e6cbb'
down_revision: Union[str, Sequence[str], None] = ('8583cfc30613', 'c3e4f5a6b7d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
