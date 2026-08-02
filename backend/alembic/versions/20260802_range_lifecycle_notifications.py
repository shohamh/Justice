import sqlalchemy as sa
from alembic import op

revision = "20260802rn01"
down_revision = "5e7f8a9b0c1d"
branch_labels = None
depends_on = None

def upgrade():
    for value in ("range_roster_changed", "range_cancelled", "range_no_show"):
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")

def downgrade():
    pass