"""Store commander-step decision notes."""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "9b7c1d2e3f4a"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("personal_constraints", sa.Column("commander_approval_note", sa.Text(), nullable=True))
    op.add_column("exemption_requests", sa.Column("commander_approval_note", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("exemption_requests", "commander_approval_note")
    op.drop_column("personal_constraints", "commander_approval_note")
