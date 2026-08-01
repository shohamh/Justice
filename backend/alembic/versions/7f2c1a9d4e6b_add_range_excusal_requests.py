"""add range excusal requests

Revision ID: 7f2c1a9d4e6b
Revises: 9d4b6c1e2f3a
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7f2c1a9d4e6b"
down_revision: str | Sequence[str] | None = "9d4b6c1e2f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    range_excusal_status_enum = postgresql.ENUM(
        "pending", "approved", "rejected", name="range_excusal_status"
    )
    range_excusal_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "range_excusal_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "range_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("range_assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "approved", "rejected", name="range_excusal_status", create_type=False
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "promoted_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("range_assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_range_excusal_requests_one_pending_per_assignment",
        "range_excusal_requests",
        ["range_assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    for notification_type in (
        "range_excusal_pending",
        "range_excusal_approved",
        "range_excusal_rejected",
        "range_reserve_promoted",
        "range_reserve_excused",
        "range_excusal_no_backfill",
    ):
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{notification_type}'")
    op.execute(
        "INSERT INTO system_settings (key, value) VALUES "
        "('mitvachim.excusal_approve_min_commander_level', '\"מדור\"') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM system_settings WHERE key = 'mitvachim.excusal_approve_min_commander_level'"
    )
    op.drop_index(
        "uq_range_excusal_requests_one_pending_per_assignment", table_name="range_excusal_requests"
    )
    op.drop_table("range_excusal_requests")
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the type.
    postgresql.ENUM(name="range_excusal_status").drop(op.get_bind(), checkfirst=True)
