"""add ahead_count and randomness_count to duty_assignments

Revision ID: f43bbf6cc6ed
Revises: 3f8a1c2d9e4b
Create Date: 2026-09-13 19:24:04.902935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f43bbf6cc6ed'
down_revision: Union[str, Sequence[str], None] = '3f8a1c2d9e4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("duty_assignments", sa.Column("ahead_count", sa.Integer, nullable=True))
    op.add_column("duty_assignments", sa.Column("randomness_count", sa.Integer, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("duty_assignments", "randomness_count")
    op.drop_column("duty_assignments", "ahead_count")
