"""Add commander_approved_by to personal_constraints and migrate pending status
to pending_commander for the new two-step approval flow

Revision ID: a1c2e3f4b5d6
Revises: 63cff804e3e4
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1c2e3f4b5d6"
down_revision = "63cff804e3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_constraints",
        sa.Column(
            "commander_approved_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.execute("UPDATE personal_constraints SET status = 'pending_commander' WHERE status = 'pending'")


def downgrade() -> None:
    op.execute(
        "UPDATE personal_constraints SET status = 'pending' "
        "WHERE status IN ('pending_commander', 'pending_duty_manager')"
    )
    op.drop_column("personal_constraints", "commander_approved_by")
