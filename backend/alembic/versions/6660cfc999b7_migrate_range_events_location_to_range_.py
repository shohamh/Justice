"""migrate range_events location to range_location_id fk

Revision ID: 6660cfc999b7
Revises: c53f4d69e63d
Create Date: 2026-08-05 22:44:02.991993

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6660cfc999b7'
down_revision: Union[str, Sequence[str], None] = 'c53f4d69e63d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Add the new FK column, nullable for now so we can backfill it.
    op.add_column(
        "range_events",
        sa.Column("range_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2. One RangeLocation row per distinct existing location string.
    distinct_locations = bind.execute(
        sa.text("SELECT DISTINCT location FROM range_events")
    ).fetchall()
    for (name,) in distinct_locations:
        bind.execute(
            sa.text(
                "INSERT INTO range_locations (id, name) VALUES (gen_random_uuid(), :name)"
            ),
            {"name": name},
        )

    # 3. Point every event at the matching new row.
    bind.execute(
        sa.text(
            "UPDATE range_events SET range_location_id = rl.id "
            "FROM range_locations rl WHERE rl.name = range_events.location"
        )
    )

    # 4. Now safe to make it required and add the FK constraint.
    op.alter_column("range_events", "range_location_id", nullable=False)
    op.create_foreign_key(
        "fk_range_events_range_location_id", "range_events", "range_locations",
        ["range_location_id"], ["id"], ondelete="RESTRICT",
    )

    # 5. Drop the old free-text column.
    op.drop_column("range_events", "location")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    op.add_column("range_events", sa.Column("location", sa.Text(), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE range_events SET location = rl.name "
            "FROM range_locations rl WHERE rl.id = range_events.range_location_id"
        )
    )
    op.alter_column("range_events", "location", nullable=False)
    op.drop_constraint("fk_range_events_range_location_id", "range_events", type_="foreignkey")
    op.drop_column("range_events", "range_location_id")
