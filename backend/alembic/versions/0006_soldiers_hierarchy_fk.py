"""add soldiers.hierarchy_node_id foreign key

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-28

The column already exists (migration 0004); this only adds the FK now that
hierarchy_nodes exists. ON DELETE SET NULL: deleting a node detaches soldiers
(node deletion is independently guarded in the service layer).
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_soldiers_hierarchy_node",
        "soldiers",
        "hierarchy_nodes",
        ["hierarchy_node_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_soldiers_hierarchy_node", "soldiers", type_="foreignkey")
