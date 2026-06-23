"""add algorithm_job_id and score columns to duty_assignments

Revision ID: 0058
Revises: 0057
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column(
            "algorithm_job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("algorithm_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("duty_assignments", sa.Column("norm_score_before", sa.Float, nullable=True))
    op.add_column("duty_assignments", sa.Column("norm_score_after", sa.Float, nullable=True))
    op.add_column("duty_assignments", sa.Column("candidate_rank", sa.Integer, nullable=True))
    op.add_column("duty_assignments", sa.Column("candidate_pool_size", sa.Integer, nullable=True))
    op.create_index(
        "idx_duty_assignments_job_id",
        "duty_assignments",
        ["algorithm_job_id"],
        postgresql_where=sa.text("algorithm_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_duty_assignments_job_id", table_name="duty_assignments")
    op.drop_column("duty_assignments", "candidate_pool_size")
    op.drop_column("duty_assignments", "candidate_rank")
    op.drop_column("duty_assignments", "norm_score_after")
    op.drop_column("duty_assignments", "norm_score_before")
    op.drop_column("duty_assignments", "algorithm_job_id")
