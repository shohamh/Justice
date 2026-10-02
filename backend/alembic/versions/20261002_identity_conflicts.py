"""identity conflicts and candidates

Revision ID: 20261002_identity_conflicts
Revises: 20261002_soldier_identity_pair
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261002_identity_conflicts"
down_revision: Union[str, Sequence[str], None] = "20261002_soldier_identity_pair"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identity_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ad_username", sa.Text(), nullable=False),
        sa.Column("personal_number", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chosen_soldier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.CheckConstraint("source IN ('sso', 'hr_sync', 'registration')",
                           name="ck_identity_conflicts_source"),
        sa.CheckConstraint("status IN ('open', 'resolved', 'dismissed')",
                           name="ck_identity_conflicts_status"),
    )
    op.create_index(
        "uq_identity_conflicts_open_source_ad_username", "identity_conflicts",
        ["source", "ad_username"], unique=True, postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "identity_conflict_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("conflict_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("identity_conflicts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("matched_fields", postgresql.ARRAY(sa.Text()), nullable=False,
                  server_default=sa.text("'{}'")),
        sa.UniqueConstraint("conflict_id", "soldier_id", name="uq_identity_conflict_candidate"),
    )
    op.create_index("ix_identity_conflict_candidates_soldier_id",
                    "identity_conflict_candidates", ["soldier_id"])


def downgrade() -> None:
    op.drop_index("ix_identity_conflict_candidates_soldier_id",
                  table_name="identity_conflict_candidates")
    op.drop_table("identity_conflict_candidates")
    op.drop_index("uq_identity_conflicts_open_source_ad_username", table_name="identity_conflicts")
    op.drop_table("identity_conflicts")
