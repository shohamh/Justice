"""add_is_commander_exemption_to_exemption_types

Revision ID: 0147aafd3359
Revises: 0ba32881b81e
Create Date: 2026-07-03 10:21:51.492359

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0147aafd3359'
down_revision: Union[str, Sequence[str], None] = '0ba32881b81e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "exemption_types",
        sa.Column(
            "is_commander_exemption",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("exemption_types", "is_commander_exemption")
