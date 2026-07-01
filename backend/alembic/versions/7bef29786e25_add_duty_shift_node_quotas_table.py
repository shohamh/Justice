"""add duty_shift_node_quotas table

Revision ID: 7bef29786e25
Revises: 0063
Create Date: 2026-06-30 23:56:39.201355

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7bef29786e25'
down_revision: Union[str, Sequence[str], None] = '0063'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "duty_shift_node_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("duty_shift_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("duty_shift_id", "hierarchy_node_id", name="uq_shift_node_quota"),
        sa.CheckConstraint("count >= 1", name="ck_shift_node_quota_count_positive"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("duty_shift_node_quotas")
