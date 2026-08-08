"""add_audit_log_range_removal_index

Revision ID: 06fced0151e1
Revises: 4446d3a826d2
Create Date: 2026-08-08 12:43:24.545588

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06fced0151e1'
down_revision: Union[str, Sequence[str], None] = '4446d3a826d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "CREATE INDEX ix_audit_log_range_removal_soldier "
        "ON audit_log ((before->>'soldier_id')) "
        "WHERE action = 'range_assignment.remove'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_audit_log_range_removal_soldier")
