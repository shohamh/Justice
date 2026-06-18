"""exclusive_end_date

Revision ID: fcac936c2558
Revises: 37feafd17119
Create Date: 2026-06-17 22:56:39.167037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fcac936c2558'
down_revision: Union[str, Sequence[str], None] = '37feafd17119'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change duty_shifts and duty_assignments end_date from inclusive-last-day
    to exclusive (first day after the duty). Adds 1 day to every existing row."""
    op.execute("UPDATE duty_shifts SET end_date = end_date + INTERVAL '1 day'")
    op.execute("UPDATE duty_assignments SET end_date = end_date + INTERVAL '1 day'")


def downgrade() -> None:
    """Revert exclusive end_date back to inclusive."""
    op.execute("UPDATE duty_shifts SET end_date = end_date - INTERVAL '1 day'")
    op.execute("UPDATE duty_assignments SET end_date = end_date - INTERVAL '1 day'")
