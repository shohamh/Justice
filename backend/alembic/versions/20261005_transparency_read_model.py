"""Store versioned, queryable transparency scores.

Revision ID: 20261005_read_model
Revises: 20261004_page_snap
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261005_read_model"
down_revision: str | Sequence[str] | None = "20261004_page_snap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transparency_read_model_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("normalization_denominator", sa.Numeric(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_transparency_read_model_current",
        "transparency_read_model_generations",
        ["source_generation", "as_of", "published_at"],
        postgresql_where=sa.text("ready"),
    )
    op.create_table(
        "transparency_read_model_rows",
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(
            "transparency_read_model_generations.id", ondelete="CASCADE",
        ), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("burden_share", sa.Numeric(), nullable=False),
        sa.Column("cumulative_score", sa.Numeric(), nullable=False),
        sa.Column("score_per_day", sa.Numeric(), nullable=False),
        sa.Column("normalised_score", sa.Numeric(), nullable=False),
        sa.Column("c_over_d", sa.Numeric(), nullable=False),
        sa.Column("active_days", sa.Integer(), nullable=False),
        sa.Column("shift_count", sa.Integer(), nullable=False),
        sa.Column("burden_share_offset_raw", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True)),
        sa.Column("node_name", sa.Text()),
        sa.Column("enrolled_at", sa.Date(), nullable=False),
        sa.Column("rank", sa.Text()),
        sa.Column("is_officer", sa.Boolean()),
        sa.Column("service_type", sa.Text()),
        sa.Column("is_globally_exempted", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_transparency_read_model_keyset",
        "transparency_read_model_rows",
        ["generation_id", sa.text("burden_share DESC"), "soldier_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transparency_read_model_keyset", table_name="transparency_read_model_rows")
    op.drop_table("transparency_read_model_rows")
    op.drop_index("ix_transparency_read_model_current", table_name="transparency_read_model_generations")
    op.drop_table("transparency_read_model_generations")
