"""create duty_assignments

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "duty_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'published'"), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'published', 'cancelled')",
            name="ck_duty_assignments_status",
        ),
    )
    op.create_index(
        "ix_duty_assignments_soldier_start", "duty_assignments", ["soldier_id", "start_date"]
    )
    op.create_index("ix_duty_assignments_dates", "duty_assignments", ["start_date", "end_date"])


def downgrade() -> None:
    op.drop_table("duty_assignments")
