"""create algorithm tables

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "algorithm_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("planning_start", sa.Date(), nullable=False),
        sa.Column("planning_end", sa.Date(), nullable=False),
        sa.Column("duty_type_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("settings_json", postgresql.JSONB(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_algorithm_jobs_status", "algorithm_jobs", ["status"])

    op.create_table(
        "reserve_assignments",
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
        sa.Column(
            "reserve_soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
    )

    op.create_table(
        "assignment_explanations",
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
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("solver_seed", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_reserve_asgn_duty_asgn", "reserve_assignments", ["duty_assignment_id"])
    op.create_index("idx_asgn_exp_duty_asgn", "assignment_explanations", ["duty_assignment_id"])


def downgrade() -> None:
    op.drop_index("idx_asgn_exp_duty_asgn", table_name="assignment_explanations", if_exists=True)
    op.drop_table("assignment_explanations")
    op.drop_index("idx_reserve_asgn_duty_asgn", table_name="reserve_assignments", if_exists=True)
    op.drop_table("reserve_assignments")
    op.drop_index("idx_algorithm_jobs_status", table_name="algorithm_jobs")
    op.drop_table("algorithm_jobs")
