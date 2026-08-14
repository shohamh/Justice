"""add rank advancement

Revision ID: db05bb8f7744
Revises: 554960f40583
Create Date: 2026-08-13 23:12:43.379585

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db05bb8f7744'
down_revision: Union[str, Sequence[str], None] = '554960f40583'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soldiers",
        sa.Column("next_rank_date_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("soldiers", sa.Column("current_rank_since", sa.Date(), nullable=True))
    op.create_table(
        "rank_advancement_intervals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("track", sa.Text(), nullable=False),
        sa.Column("rank", sa.Text(), nullable=False),
        sa.Column("months_to_next", sa.Integer(), nullable=True),
        sa.UniqueConstraint("track", "rank", name="uq_rank_advancement_interval_track_rank"),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'rank_advanced'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'rank_advancement_soon'")


def downgrade() -> None:
    op.drop_table("rank_advancement_intervals")
    op.drop_column("soldiers", "current_rank_since")
    op.drop_column("soldiers", "next_rank_date_overridden")
    # Postgres cannot drop enum values; matches the existing repo convention
    # (see a3f1c9d7e2b4_add_range_covers_duty_info_type.py) of not reversing
    # ALTER TYPE ... ADD VALUE in downgrade.
