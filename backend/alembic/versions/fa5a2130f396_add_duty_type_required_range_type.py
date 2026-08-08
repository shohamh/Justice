"""add_duty_type_required_range_type

Revision ID: fa5a2130f396
Revises: 6660cfc999b7
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'fa5a2130f396'
down_revision: Union[str, Sequence[str], None] = '6660cfc999b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_types",
        sa.Column(
            "required_range_type",
            postgresql.ENUM("laser", "live", "alal", name="range_type", create_type=False),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE duty_types SET required_range_type = 'laser' WHERE requires_weapon = true"
    )


def downgrade() -> None:
    op.drop_column("duty_types", "required_range_type")
