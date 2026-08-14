"""add advance_on_career_entry to rank_advancement_intervals

Revision ID: 2c93124c3a99
Revises: 92afb4359c3b
Create Date: 2026-08-14 13:50:21.895193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c93124c3a99'
down_revision: Union[str, Sequence[str], None] = '92afb4359c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rank_advancement_intervals",
        sa.Column("advance_on_career_entry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("rank_advancement_intervals", "advance_on_career_entry")
