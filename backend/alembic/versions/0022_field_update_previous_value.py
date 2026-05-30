"""add previous_value to soldier_field_updates

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "soldier_field_updates",
        sa.Column("previous_value", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soldier_field_updates", "previous_value")
