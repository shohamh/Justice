"""Persist bounded transparency page views.

Revision ID: 20261004_page_snap
Revises: 20261004_src_gen
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261004_page_snap"
down_revision: str | Sequence[str] | None = "20261004_src_gen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transparency_page_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("binding", sa.Text(), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("can_see_exemption_aggregates", sa.Boolean(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_transparency_page_snapshot_reuse",
        "transparency_page_snapshots",
        ["binding", "source_generation", "as_of", "expires_at"],
    )
    op.create_index(
        "ix_transparency_page_snapshot_expiry",
        "transparency_page_snapshots",
        ["expires_at", "id"],
    )
    op.create_table(
        "transparency_page_snapshot_rows",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transparency_page_snapshots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "ordinal",
            sa.Integer(),
            primary_key=True,
            comment="Zero-based chunk ordinal; each chunk contains up to 100 ordered rows.",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            comment="JSON array of up to 100 ordered transparency rows.",
        ),
    )


def downgrade() -> None:
    op.drop_table("transparency_page_snapshot_rows")
    op.drop_index("ix_transparency_page_snapshot_expiry", table_name="transparency_page_snapshots")
    op.drop_index("ix_transparency_page_snapshot_reuse", table_name="transparency_page_snapshots")
    op.drop_table("transparency_page_snapshots")
