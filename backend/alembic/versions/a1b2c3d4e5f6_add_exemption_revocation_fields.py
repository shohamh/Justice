"""Add revocation fields to soldier_exemptions and exemption_revoked notification type

Revision ID: a1b2c3d4e5f6
Revises: d98e78b867e5
Create Date: 2026-07-06

"""
import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "d98e78b867e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soldier_exemptions", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("soldier_exemptions", sa.Column("revoked_by", sa.UUID(), nullable=True))
    op.add_column("soldier_exemptions", sa.Column("revoke_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "soldier_exemptions_revoked_by_fkey",
        "soldier_exemptions", "soldiers",
        ["revoked_by"], ["id"], ondelete="SET NULL",
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'exemption_revoked'")


def downgrade() -> None:
    op.drop_constraint("soldier_exemptions_revoked_by_fkey", "soldier_exemptions", type_="foreignkey")
    op.drop_column("soldier_exemptions", "revoke_reason")
    op.drop_column("soldier_exemptions", "revoked_by")
    op.drop_column("soldier_exemptions", "revoked_at")
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the enum.
