"""add FK indexes for performance

Revision ID: 0062
Revises: 0061
Create Date: 2026-06-29
"""
from alembic import op

revision = '0062'
down_revision = '0061'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_soldiers_hierarchy_node_id", "soldiers", ["hierarchy_node_id"])
    op.create_index("ix_duty_assignments_soldier_id", "duty_assignments", ["soldier_id"])
    op.create_index("ix_duty_assignments_duty_type_id", "duty_assignments", ["duty_type_id"])
    op.create_index("ix_soldier_exemptions_soldier_id", "soldier_exemptions", ["soldier_id"])
    op.create_index("ix_algorithm_jobs_created_by", "algorithm_jobs", ["created_by"])
    op.create_index("ix_personal_constraints_soldier_id", "personal_constraints", ["soldier_id"])


def downgrade() -> None:
    op.drop_index("ix_personal_constraints_soldier_id", "personal_constraints")
    op.drop_index("ix_algorithm_jobs_created_by", "algorithm_jobs")
    op.drop_index("ix_soldier_exemptions_soldier_id", "soldier_exemptions")
    op.drop_index("ix_duty_assignments_duty_type_id", "duty_assignments")
    op.drop_index("ix_duty_assignments_soldier_id", "duty_assignments")
    op.drop_index("ix_soldiers_hierarchy_node_id", "soldiers")
