"""swap approval decision log

Revision ID: 5c504eb679a0
Revises: dbb2a58b0f63
Create Date: 2026-07-22 13:39:50.052738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5c504eb679a0'
down_revision: Union[str, Sequence[str], None] = 'dbb2a58b0f63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add per-decision rejection columns to swap approval tables, plus a
    uniqueness guard on (swap_request_id, side, commander_id, approver_kind)."""
    op.add_column("swap_manager_approvals", sa.Column("rejected", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("swap_manager_approvals", sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("swap_manager_approvals", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_swap_manager_approvals_rejected_by_soldiers", "swap_manager_approvals", "soldiers",
        ["rejected_by"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_swap_manager_approval_request_side_person_kind", "swap_manager_approvals",
        ["swap_request_id", "side", "commander_id", "approver_kind"],
    )
    op.add_column("swap_requests", sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_swap_requests_rejected_by_soldiers", "swap_requests", "soldiers",
        ["rejected_by"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    """Revert the per-decision rejection columns and uniqueness guard."""
    op.drop_constraint("fk_swap_requests_rejected_by_soldiers", "swap_requests", type_="foreignkey")
    op.drop_column("swap_requests", "rejected_by")
    op.drop_constraint("uq_swap_manager_approval_request_side_person_kind", "swap_manager_approvals", type_="unique")
    op.drop_constraint("fk_swap_manager_approvals_rejected_by_soldiers", "swap_manager_approvals", type_="foreignkey")
    op.drop_column("swap_manager_approvals", "rejected_at")
    op.drop_column("swap_manager_approvals", "rejected_by")
    op.drop_column("swap_manager_approvals", "rejected")
