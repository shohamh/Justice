"""add_linked_commander_exemption_id

Revision ID: 1a5c77b91db5
Revises: d98e78b867e5
Create Date: 2026-07-05 07:37:36.752594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1a5c77b91db5'
down_revision: Union[str, Sequence[str], None] = 'd98e78b867e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exemption_requests",
        sa.Column(
            "linked_commander_exemption_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldier_exemptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "exemption_requests_linked_commander_exemption_id_fkey",
        "exemption_requests",
        type_="foreignkey",
    )
    op.drop_column("exemption_requests", "linked_commander_exemption_id")
