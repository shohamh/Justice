"""add_soldier_profile_picture

Revision ID: d6f7a12679be
Revises: 5fe19e1d2a31
Create Date: 2026-06-17 21:22:02.111492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6f7a12679be'
down_revision: Union[str, Sequence[str], None] = '5fe19e1d2a31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("profile_picture_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("soldiers", "profile_picture_url")
