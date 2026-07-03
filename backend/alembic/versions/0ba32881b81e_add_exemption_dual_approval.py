"""add_exemption_dual_approval

Revision ID: 0ba32881b81e
Revises: 52cd8f7417e1
Create Date: 2026-07-03 09:29:28.660519

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0ba32881b81e'
down_revision: Union[str, Sequence[str], None] = '52cd8f7417e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exemption_requests",
        sa.Column("commander_approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute("UPDATE exemption_requests SET status = 'pending_commander' WHERE status = 'pending'")


def downgrade() -> None:
    op.execute("UPDATE exemption_requests SET status = 'pending' WHERE status = 'pending_commander'")
    op.drop_column("exemption_requests", "commander_approved_by")
