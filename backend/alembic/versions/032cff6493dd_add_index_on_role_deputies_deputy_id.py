"""add index on role_deputies.deputy_id

Revision ID: 032cff6493dd
Revises: bccac29dd1b5
Create Date: 2026-08-20 22:12:16.517343

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '032cff6493dd'
down_revision: Union[str, Sequence[str], None] = 'bccac29dd1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_role_deputies_deputy_id", "role_deputies", ["deputy_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_role_deputies_deputy_id", table_name="role_deputies")
