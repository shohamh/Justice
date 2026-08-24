"""add soldier food type and constraints

Revision ID: d8e9f0a1b2c3
Revises: a2b3c4d5e6f7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FOOD_TYPE_ENUM = sa.Enum(
    "regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin",
    name="food_type",
)


def upgrade() -> None:
    FOOD_TYPE_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column("soldiers", sa.Column("food_type", FOOD_TYPE_ENUM, nullable=True))
    op.add_column("soldiers", sa.Column("food_constraints", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("soldiers", "food_constraints")
    op.drop_column("soldiers", "food_type")
    FOOD_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
