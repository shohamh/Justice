"""Add timestamps for commander-step approvals."""
from alembic import op
import sqlalchemy as sa

revision = "9b7c1d2e3f4a"
down_revision = "366b35d4cff5"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("personal_constraints", sa.Column("commander_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("exemption_requests", sa.Column("commander_approved_at", sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column("exemption_requests", "commander_approved_at")
    op.drop_column("personal_constraints", "commander_approved_at")
