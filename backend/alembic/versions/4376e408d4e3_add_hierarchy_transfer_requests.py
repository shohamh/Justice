"""add hierarchy transfer requests

Revision ID: 4376e408d4e3
Revises: 3dd30881eefd
Create Date: 2026-07-20 21:13:05.568036

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4376e408d4e3'
down_revision: Union[str, Sequence[str], None] = '3dd30881eefd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hierarchy_transfer_requests",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_node_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id"), nullable=True),
        sa.Column("to_node_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("requested_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id"), nullable=False),
        sa.Column("decided_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'transfer_request_pending'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'transfer_request_rejected'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("hierarchy_transfer_requests")
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the enum.
