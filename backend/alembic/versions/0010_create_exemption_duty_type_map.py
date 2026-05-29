"""create exemption_duty_type_map

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-29
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exemption_duty_type_map",
        sa.Column("exemption_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("duty_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("duty_types.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("exemption_duty_type_map")
