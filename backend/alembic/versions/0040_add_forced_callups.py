"""add forced_callups table

Revision ID: 0040
Revises: 0039
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forced_callups",
        sa.Column("id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("initiator_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("pulled_soldier_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("original_assignment_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("pull_date", sa.Date(), nullable=False),
        sa.Column("replacement_soldier_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("replacement_assignment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "approved", "rejected", name="forced_callup_status", create_type=True),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("approver_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callup_multiplier", sa.Numeric(5, 2), nullable=False, server_default="2.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("forced_callups_pkey")),
    )


def downgrade() -> None:
    op.drop_table("forced_callups")
    op.execute("DROP TYPE IF EXISTS forced_callup_status")
