"""fix duty_assignments status check constraint to include algorithm statuses

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-02

"""
import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_duty_assignments_status", "duty_assignments", type_="check")
    op.create_check_constraint(
        "ck_duty_assignments_status",
        "duty_assignments",
        "status IN ('proposed', 'published', 'cancelled', 'algorithm_draft', 'algorithm_rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_duty_assignments_status", "duty_assignments", type_="check")
    op.create_check_constraint(
        "ck_duty_assignments_status",
        "duty_assignments",
        "status IN ('proposed', 'published', 'cancelled')",
    )
