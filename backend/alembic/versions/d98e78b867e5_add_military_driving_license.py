"""add_military_driving_license

Revision ID: d98e78b867e5
Revises: 4f9731b4a496
Create Date: 2026-07-04 12:02:25.762413

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd98e78b867e5'
down_revision: Union[str, Sequence[str], None] = '4f9731b4a496'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("has_military_driving_license", sa.Boolean(), nullable=True))
    op.add_column("soldiers", sa.Column("military_driving_license_expiry", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("soldiers", "military_driving_license_expiry")
    op.drop_column("soldiers", "has_military_driving_license")
