"""create hierarchy_nodes

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Top-down order. create_table emits CREATE TYPE for this named enum once;
# do NOT also call LEVEL_ENUM.create() (that double-creates — see slice 1 migration 0004).
LEVEL_ENUM = sa.Enum("department", "branch", "group", "team", name="hierarchy_level")


def upgrade() -> None:
    op.create_table(
        "hierarchy_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("level", LEVEL_ENUM, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("commander_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("path_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_hierarchy_nodes_parent_id", "hierarchy_nodes", ["parent_id"])
    op.create_index("ix_hierarchy_nodes_level", "hierarchy_nodes", ["level"])
    op.create_index("ix_hierarchy_nodes_commander_id", "hierarchy_nodes", ["commander_id"])
    op.create_index("ix_hierarchy_nodes_path_ids", "hierarchy_nodes", ["path_ids"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("hierarchy_nodes")
    LEVEL_ENUM.drop(op.get_bind(), checkfirst=True)
