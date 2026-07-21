"""add approver_kind to swap_manager_approvals

Revision ID: dbb2a58b0f63
Revises: 4376e408d4e3
Create Date: 2026-07-21 08:31:44.664985

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dbb2a58b0f63'
down_revision: Union[str, Sequence[str], None] = '4376e408d4e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "swap_manager_approvals",
        sa.Column("approver_kind", sa.Text(), nullable=False, server_default="commander"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("swap_manager_approvals", "approver_kind")
