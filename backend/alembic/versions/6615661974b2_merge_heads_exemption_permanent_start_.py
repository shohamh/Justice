"""merge heads exemption permanent start_date and range covers duty info type

Revision ID: 6615661974b2
Revises: a3f1c9d7e2b4, b0dc843e6594
Create Date: 2026-08-12 21:29:24.074975

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6615661974b2'
down_revision: Union[str, Sequence[str], None] = ('a3f1c9d7e2b4', 'b0dc843e6594')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
