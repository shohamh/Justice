"""create duty_day_overrides

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_day_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "duty_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "effective_soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "duty_assignment_id", "date", name="uq_duty_day_overrides_assignment_date"
        ),
        sa.CheckConstraint(
            "reason IN ('replacement', 'no_show_covered', 'cancelled', 'manual_edit')",
            name="ck_duty_day_overrides_reason",
        ),
    )


def downgrade() -> None:
    op.drop_table("duty_day_overrides")
