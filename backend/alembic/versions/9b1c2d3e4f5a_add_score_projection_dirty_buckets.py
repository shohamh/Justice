"""add score projection dirty buckets

Revision ID: 9b1c2d3e4f5a
Revises: 6a7b8c9d0e1f
Create Date: 2026-08-21 22:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9b1c2d3e4f5a"
down_revision: Union[str, Sequence[str], None] = "6a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "score_projection_dirty_buckets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quarter_start", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'dirty'")),
        sa.Column("old_node_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("new_node_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("divergence", postgresql.JSONB(), nullable=True),
        sa.Column(
            "dirtied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("soldier_id", "quarter_start", name="uq_score_projection_dirty_bucket"),
    )
    op.create_index(
        "ix_score_projection_dirty_buckets_status",
        "score_projection_dirty_buckets",
        ["status"],
    )
    op.create_index(
        "ix_score_projection_dirty_buckets_quarter",
        "score_projection_dirty_buckets",
        ["quarter_start"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_score_projection_dirty_buckets_quarter", table_name="score_projection_dirty_buckets")
    op.drop_index("ix_score_projection_dirty_buckets_status", table_name="score_projection_dirty_buckets")
    op.drop_table("score_projection_dirty_buckets")
