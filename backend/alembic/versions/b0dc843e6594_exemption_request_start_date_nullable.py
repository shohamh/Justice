"""exemption_request start_date nullable

Revision ID: b0dc843e6594
Revises: 6fab7ceeba84
Create Date: 2026-08-11 22:38:37.150426

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0dc843e6594'
down_revision: Union[str, Sequence[str], None] = '6fab7ceeba84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "exemption_requests", "start_date",
        existing_type=sa.Date(), nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "exemption_requests", "start_date",
        existing_type=sa.Date(), nullable=False,
    )
