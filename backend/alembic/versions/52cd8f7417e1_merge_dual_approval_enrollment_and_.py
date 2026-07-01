"""merge dual-approval enrollment and import-sessions/shift-quotas heads

Revision ID: 52cd8f7417e1
Revises: 0064, 3e5a43da5e0e
Create Date: 2026-07-01 19:16:40.277829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52cd8f7417e1'
down_revision: Union[str, Sequence[str], None] = ('0064', '3e5a43da5e0e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
