"""add_theme_preference_to_soldiers

Revision ID: 0065
Revises: 71e217f7c372
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0065'
down_revision: Union[str, Sequence[str], None] = '71e217f7c372'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soldiers",
        sa.Column("theme_preference", sa.Text(), nullable=False, server_default="system"),
    )


def downgrade() -> None:
    op.drop_column("soldiers", "theme_preference")
