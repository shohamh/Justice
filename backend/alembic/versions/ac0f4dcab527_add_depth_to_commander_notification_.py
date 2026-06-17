"""add_depth_to_commander_notification_scopes

Revision ID: ac0f4dcab527
Revises: 1506edfdeb2b
Create Date: 2026-06-17 20:49:32.259480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac0f4dcab527'
down_revision: Union[str, Sequence[str], None] = '1506edfdeb2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "commander_notification_scopes",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="-1"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("commander_notification_scopes", "depth")
