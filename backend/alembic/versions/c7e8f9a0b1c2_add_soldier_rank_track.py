"""add persisted soldier rank track

Revision ID: c7e8f9a0b1c2
Revises: 2c93124c3a99
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "2c93124c3a99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("rank_track", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE soldiers
            SET rank_track = CASE
                WHEN rank IN ('קמא', 'קאב', 'קאם') THEN 'officer_academic'
                WHEN rank IN ('סגמ', 'סגן', 'סרן', 'רסן', 'סאל', 'אלמ', 'תאל', 'אלוף', 'רב אלוף') THEN 'officer'
                WHEN rank IN ('טוראי', 'רבט', 'סמל', 'סמר', 'רסל', 'רסר', 'רסמ', 'רסב', 'רנג') THEN 'enlisted'
                ELSE NULL
            END
            WHERE rank IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("soldiers", "rank_track")
