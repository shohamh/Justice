"""add range lifecycle fields

Revision ID: 5e7f8a9b0c1d
Revises: f4a1b2c3d4e5
"""

import sqlalchemy as sa

from alembic import op

revision = "5e7f8a9b0c1d"
down_revision = "f4a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("range_events", sa.Column("cancellation_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("range_events", "cancellation_reason")
