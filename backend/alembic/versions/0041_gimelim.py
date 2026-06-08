"""Add is_gimelim to duty_dismissals and gimelim notification types

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_gimelim flag to duty_dismissals
    op.add_column(
        "duty_dismissals",
        sa.Column("is_gimelim", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # Add four gimelim notification types to the existing PG enum
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'gimelim_dismissed'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'gimelim_reserve_called_up'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'gimelim_demoted_to_reserve'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'gimelim_reassigned'")


def downgrade() -> None:
    op.drop_column("duty_dismissals", "is_gimelim")
    # PG enum values cannot be removed without recreating the type;
    # downgrade leaves the enum values in place (safe — unused values are harmless)
