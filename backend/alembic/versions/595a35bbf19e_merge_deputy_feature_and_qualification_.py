"""merge deputy feature and qualification-expiry-notifications heads

Revision ID: 595a35bbf19e
Revises: 032cff6493dd, b7c8d9e0f1a2
Create Date: 2026-08-20 23:04:12.957787

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '595a35bbf19e'
down_revision: Union[str, Sequence[str], None] = ('032cff6493dd', 'b7c8d9e0f1a2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
