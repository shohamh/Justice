"""add_potential

Revision ID: 4f9731b4a496
Revises: 52cd8f7417e1
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '4f9731b4a496'
down_revision: Union[str, Sequence[str], None] = '52cd8f7417e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exemption_types",
        sa.Column("is_commander_exemption", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("soldiers", sa.Column("next_rank_date", sa.Date(), nullable=True))
    op.create_table(
        "potential_modifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_potential_modifiers_node", "potential_modifiers", ["hierarchy_node_id"])


def downgrade() -> None:
    op.drop_index("ix_potential_modifiers_node", table_name="potential_modifiers")
    op.drop_table("potential_modifiers")
    op.drop_column("soldiers", "next_rank_date")
    op.drop_column("exemption_types", "is_commander_exemption")
