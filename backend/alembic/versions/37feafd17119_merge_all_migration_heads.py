"""merge all migration heads

Revision ID: 37feafd17119
Revises: d6f7a12679be, e1a591172b65
Create Date: 2026-06-17 22:22:45.216945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37feafd17119'
down_revision: Union[str, Sequence[str], None] = ('d6f7a12679be', 'e1a591172b65')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
