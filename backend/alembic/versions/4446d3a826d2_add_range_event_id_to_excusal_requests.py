"""add_range_event_id_to_excusal_requests

Revision ID: 4446d3a826d2
Revises: 6660cfc999b7
Create Date: 2026-08-07 22:11:56.890191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4446d3a826d2'
down_revision: Union[str, Sequence[str], None] = '6660cfc999b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "range_excusal_requests",
        sa.Column(
            "range_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("range_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE range_excusal_requests r
        SET range_event_id = a.range_event_id
        FROM range_assignments a
        WHERE r.range_assignment_id = a.id
        """
    )


def downgrade() -> None:
    op.drop_column("range_excusal_requests", "range_event_id")
