"""add range reminder fields and notification types"""
from alembic import op
import sqlalchemy as sa
revision = "f4a1b2c3d4e5"
down_revision = "7f2c1a9d4e6b"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("range_events", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_reminder'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_reminder_shortfall'")

def downgrade():
    op.drop_column("range_events", "reminder_sent_at")
