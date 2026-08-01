"""drop_soldier_range_qualification_unique

Revision ID: 619962785231
Revises: de2742d45fa3
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '619962785231'
down_revision: Union[str, Sequence[str], None] = 'de2742d45fa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_soldier_range_qualification", "soldier_range_qualifications", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_soldier_range_qualification", "soldier_range_qualifications", ["soldier_id", "range_type"],
    )
