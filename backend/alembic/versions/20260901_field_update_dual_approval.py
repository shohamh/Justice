"""add staged approval metadata for retrospective field updates"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901_field_update_dual"
down_revision = "20260901_active_days_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soldier_field_updates", sa.Column("commander_approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True))
    op.add_column("soldier_field_updates", sa.Column("commander_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("soldier_field_updates", sa.Column("commander_approval_note", sa.Text(), nullable=True))
    op.add_column("soldier_field_updates", sa.Column("duty_manager_approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True))
    op.add_column("soldier_field_updates", sa.Column("duty_manager_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_soldier_field_updates_one_active",
        "soldier_field_updates",
        ["soldier_id", "field_name"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'pending_commander', 'pending_duty_manager')"
        ),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'field_update_pending'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'field_update_approved'")


def downgrade() -> None:
    op.drop_index("uq_soldier_field_updates_one_active", table_name="soldier_field_updates")
    op.drop_column("soldier_field_updates", "duty_manager_approved_at")
    op.drop_column("soldier_field_updates", "duty_manager_approved_by")
    op.drop_column("soldier_field_updates", "commander_approval_note")
    op.drop_column("soldier_field_updates", "commander_approved_at")
    op.drop_column("soldier_field_updates", "commander_approved_by")
