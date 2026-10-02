"""merge Exchange and storage migration heads

Revision ID: 366e272a0dae
Revises: 20261002_exchange_event_date, 4858092e72e7
Create Date: 2026-10-02 18:59:11.686515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '366e272a0dae'
down_revision: Union[str, Sequence[str], None] = ('20261002_exchange_event_date', '4858092e72e7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
