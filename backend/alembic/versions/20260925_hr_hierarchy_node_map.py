"""Add hr_hierarchy_node_map table

Revision ID: 20260925_hr_hierarchy_node_map
Revises: 20260924_hr_hierarchy_sync
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260925_hr_hierarchy_node_map"
down_revision = "20260924_hr_hierarchy_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_hierarchy_node_map",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hr_group_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=False, unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hr_hierarchy_node_map")
