"""add CHECK constraints for date integrity

Revision ID: 0063
Revises: 0062
Create Date: 2026-06-29
"""
from alembic import op

revision = '0063'
down_revision = '0062'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_duty_assignments_dates",
        "duty_assignments",
        "start_date <= end_date",
    )
    op.create_check_constraint(
        "ck_personal_constraints_dates",
        "personal_constraints",
        "start_date <= end_date",
    )
    op.create_check_constraint(
        "ck_exemption_requests_dates",
        "exemption_requests",
        "start_date <= end_date OR end_date IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_exemption_requests_dates", "exemption_requests")
    op.drop_constraint("ck_personal_constraints_dates", "personal_constraints")
    op.drop_constraint("ck_duty_assignments_dates", "duty_assignments")
