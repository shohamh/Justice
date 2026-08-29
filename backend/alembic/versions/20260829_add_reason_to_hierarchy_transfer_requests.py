"""add reason to hierarchy transfer requests"""
from alembic import op
import sqlalchemy as sa

revision = "20260829_transfer_reason"
down_revision = "20260829rar1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hierarchy_transfer_requests", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("hierarchy_transfer_requests", "reason")
