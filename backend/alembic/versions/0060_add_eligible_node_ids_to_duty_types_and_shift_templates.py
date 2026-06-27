"""add eligible_node_ids to duty_types and shift_templates

Revision ID: 0060
Revises: 0059
Create Date: 2026-06-26 09:19:59.620466

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0060'
down_revision: Union[str, Sequence[str], None] = '0059'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_types",
        sa.Column("eligible_node_ids", postgresql.ARRAY(sa.UUID(as_uuid=True)), nullable=True),
    )
    op.add_column(
        "shift_templates",
        sa.Column("eligible_node_ids", postgresql.ARRAY(sa.UUID(as_uuid=True)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shift_templates", "eligible_node_ids")
    op.drop_column("duty_types", "eligible_node_ids")
