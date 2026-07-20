"""add_swap_manager_approvals

Revision ID: b388b74fdae9
Revises: 3dd30881eefd
Create Date: 2026-07-09 07:54:44.695298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b388b74fdae9"
down_revision: Union[str, Sequence[str], None] = "3dd30881eefd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "swap_manager_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("swap_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("swap_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("commander_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_swap_manager_approvals_swap_request_id",
        "swap_manager_approvals",
        ["swap_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_swap_manager_approvals_swap_request_id", table_name="swap_manager_approvals")
    op.drop_table("swap_manager_approvals")
