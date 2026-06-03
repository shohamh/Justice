"""duty_manager_scope table — multi-node DM scoping, seeds existing DMs

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_manager_scope",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), primary_key=True,
        ),
        sa.Column("duty_manager_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["duty_manager_id"], ["soldiers.id"],
            ondelete="CASCADE", name="fk_dm_scope_soldier",
        ),
        sa.ForeignKeyConstraint(
            ["hierarchy_node_id"], ["hierarchy_nodes.id"],
            ondelete="CASCADE", name="fk_dm_scope_node",
        ),
        sa.UniqueConstraint("duty_manager_id", "hierarchy_node_id", name="uq_dm_scope"),
    )
    # Seed existing duty managers from their current hierarchy_node_id
    op.get_bind().execute(sa.text("""
        INSERT INTO duty_manager_scope (id, duty_manager_id, hierarchy_node_id)
        SELECT gen_random_uuid(), id, hierarchy_node_id
        FROM soldiers
        WHERE role = 'duty_manager' AND hierarchy_node_id IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_table("duty_manager_scope")
