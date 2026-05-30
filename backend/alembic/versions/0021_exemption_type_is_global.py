"""add is_global flag to exemption_types

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exemption_types",
        sa.Column("is_global", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("exemption_types", "is_global")
