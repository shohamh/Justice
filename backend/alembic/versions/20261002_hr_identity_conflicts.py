"""HR sync identity conflicts and preferred records

Revision ID: 20261002_hr_identity_conflicts
Revises: 20261002_identity_conflicts
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261002_hr_identity_conflicts"
down_revision: Union[str, Sequence[str], None] = "20261002_identity_conflicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hr_person_syncs",
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "hr_identity_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("personal_number", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("applied_index", sa.Integer(), nullable=True),
        sa.Column("colliding_soldier_ids", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("hr_person_sync_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("hr_person_syncs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chosen_index", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('duplicate_personal_number', 'email_collision', "
            "'ad_username_collision', 'email_invalid')",
            name="ck_hr_identity_conflicts_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')", name="ck_hr_identity_conflicts_status"
        ),
    )
    op.create_index(
        "uq_hr_identity_conflicts_active", "hr_identity_conflicts",
        ["personal_number", "kind"], unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )
    op.create_table(
        "hr_preferred_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("personal_number", sa.Text(), nullable=False, unique=True),
        sa.Column("key_type", sa.Text(), nullable=False),
        sa.Column("key_value", sa.Text(), nullable=False),
        sa.Column("chosen_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "key_type IN ('t_person_id', 'username', 'mail')", name="ck_hr_preferred_records_key_type"
        ),
    )


def downgrade() -> None:
    op.drop_table("hr_preferred_records")
    op.drop_index("uq_hr_identity_conflicts_active", table_name="hr_identity_conflicts")
    op.drop_table("hr_identity_conflicts")
    op.drop_column("hr_person_syncs", "conflict_count")
