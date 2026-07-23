"""create exemption duty location map

Revision ID: 8c211fe562d5
Revises: dbb2a58b0f63
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "8c211fe562d5"
down_revision = "dbb2a58b0f63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exemption_duty_location_map",
        sa.Column(
            "exemption_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exemption_types.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_locations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("exemption_duty_location_map")
