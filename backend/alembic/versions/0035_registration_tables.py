"""registration_invite_codes and soldier_enrollment_requests tables

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-03

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_invite_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("uses_left", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], name="fk_invite_code_creator", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "soldier_enrollment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], name="fk_enrollment_soldier", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_node_id"], ["hierarchy_nodes.id"], name="fk_enrollment_node", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by"], ["soldiers.id"], name="fk_enrollment_decider", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_enrollment_requests_status", "soldier_enrollment_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_enrollment_requests_status", table_name="soldier_enrollment_requests")
    op.drop_table("soldier_enrollment_requests")
    op.drop_table("registration_invite_codes")
