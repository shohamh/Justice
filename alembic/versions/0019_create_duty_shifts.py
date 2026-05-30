"""create duty_shifts and add duty_shift_id to duty_assignments

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_shifts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
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
        sa.Column("required_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("required_count >= 1", name="chk_required_count_positive"),
    )
    op.create_index("idx_duty_shifts_dates", "duty_shifts", ["start_date", "end_date"])
    op.create_index("idx_duty_shifts_type", "duty_shifts", ["duty_type_id"])

    op.add_column(
        "duty_assignments",
        sa.Column(
            "duty_shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_shifts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_da_shift", "duty_assignments", ["duty_shift_id"])


def downgrade() -> None:
    op.drop_index("idx_da_shift", table_name="duty_assignments")
    op.drop_column("duty_assignments", "duty_shift_id")
    op.drop_index("idx_duty_shifts_type", table_name="duty_shifts")
    op.drop_index("idx_duty_shifts_dates", table_name="duty_shifts")
    op.drop_table("duty_shifts")
