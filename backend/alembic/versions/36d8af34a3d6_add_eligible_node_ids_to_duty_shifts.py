"""add eligible_node_ids to duty_shifts

Revision ID: 36d8af34a3d6
Revises: 0025
Create Date: 2026-06-01 07:34:09.544282

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '36d8af34a3d6'
down_revision: Union[str, Sequence[str], None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_shifts",
        sa.Column(
            "eligible_node_ids",
            postgresql.ARRAY(sa.UUID(as_uuid=True)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("duty_shifts", "eligible_node_ids")
