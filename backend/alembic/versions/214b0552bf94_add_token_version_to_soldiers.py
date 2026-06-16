"""add_token_version_to_soldiers

Revision ID: 214b0552bf94
Revises: 0049
Create Date: 2026-06-16 16:11:53.097143

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '214b0552bf94'
down_revision: Union[str, Sequence[str], None] = '0049'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soldiers",
        sa.Column("token_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("soldiers", "token_version")
