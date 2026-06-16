"""add_lockout_columns_to_soldiers

Revision ID: 1506edfdeb2b
Revises: 214b0552bf94
Create Date: 2026-06-16 16:24:46.578732

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1506edfdeb2b'
down_revision: Union[str, Sequence[str], None] = '214b0552bf94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soldiers",
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "soldiers",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soldiers", "locked_until")
    op.drop_column("soldiers", "failed_login_count")
