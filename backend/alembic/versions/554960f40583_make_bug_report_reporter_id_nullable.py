"""make bug report reporter_id nullable

Revision ID: 554960f40583
Revises: 6615661974b2
Create Date: 2026-08-13 21:09:06.661678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '554960f40583'
down_revision: Union[str, Sequence[str], None] = '6615661974b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("bug_reports", "reporter_id", nullable=True)
    op.drop_constraint("bug_reports_reporter_id_fkey", "bug_reports", type_="foreignkey")
    op.create_foreign_key(
        "bug_reports_reporter_id_fkey",
        "bug_reports",
        "soldiers",
        ["reporter_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("bug_reports_reporter_id_fkey", "bug_reports", type_="foreignkey")
    op.create_foreign_key(
        "bug_reports_reporter_id_fkey",
        "bug_reports",
        "soldiers",
        ["reporter_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("bug_reports", "reporter_id", nullable=False)
