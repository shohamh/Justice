"""merge ranges_in_duty_history and weapon_qualification_eligibility heads

Revision ID: ffe105dad988
Revises: 06fced0151e1, 55bf8c15f4b3
Create Date: 2026-08-08 17:53:54.468241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffe105dad988'
down_revision: Union[str, Sequence[str], None] = ('06fced0151e1', '55bf8c15f4b3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
