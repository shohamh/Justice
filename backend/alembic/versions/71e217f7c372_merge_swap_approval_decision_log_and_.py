"""merge swap approval decision log and exemption duty location map

Revision ID: 71e217f7c372
Revises: 5c504eb679a0, 8c211fe562d5
Create Date: 2026-07-24 17:42:17.480256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71e217f7c372'
down_revision: Union[str, Sequence[str], None] = ('5c504eb679a0', '8c211fe562d5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
