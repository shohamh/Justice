"""create soldiers

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


ROLE_ENUM = sa.Enum("soldier", "commander", "duty_manager", "admin", name="soldier_role")


def upgrade() -> None:
    # create_table emits CREATE TYPE for the named enum; no explicit .create() needed.
    op.create_table(
        "soldiers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("personal_number", sa.Text(), nullable=False, unique=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", ROLE_ENUM, nullable=False, server_default="soldier"),
        sa.Column("hierarchy_node_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),  # FK added in slice 2
        sa.Column("enrolled_at", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("left_at", sa.Date(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_soldiers_personal_number", "soldiers", ["personal_number"], unique=True)
    op.create_index("ix_soldiers_role", "soldiers", ["role"])
    op.create_index("ix_soldiers_active", "soldiers", ["left_at"])


def downgrade() -> None:
    op.drop_table("soldiers")
    ROLE_ENUM.drop(op.get_bind(), checkfirst=True)
