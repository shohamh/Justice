"""add_range_assignment_is_draft

Revision ID: 7a13f6c9b8e2
Revises: 619962785231
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a13f6c9b8e2'
down_revision: Union[str, Sequence[str], None] = '619962785231'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "range_assignments",
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("range_assignments", "is_draft")
