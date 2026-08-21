"""add score projection tables

Revision ID: 6a7b8c9d0e1f
Revises: 595a35bbf19e
Create Date: 2026-08-21 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, Sequence[str], None] = "595a35bbf19e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "soldier_score_projection",
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("projection_version", sa.Text(), nullable=False),
        sa.Column("duty_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("adjustment_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("cumulative_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("shift_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "soldier_quarter_score_projection",
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("quarter_start", sa.Date(), primary_key=True, nullable=False),
        sa.Column("projection_version", sa.Text(), nullable=False),
        sa.Column("duty_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("adjustment_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("shift_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_fingerprint", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_soldier_quarter_score_projection_soldier_id",
        "soldier_quarter_score_projection",
        ["soldier_id"],
    )
    op.create_index(
        "ix_soldier_quarter_score_projection_quarter_start",
        "soldier_quarter_score_projection",
        ["quarter_start"],
    )
    op.create_index(
        "ix_soldier_quarter_score_projection_soldier_quarter",
        "soldier_quarter_score_projection",
        ["soldier_id", "quarter_start"],
        unique=True,
    )

    op.create_table(
        "score_projection_quarter_total",
        sa.Column("quarter_start", sa.Date(), primary_key=True, nullable=False),
        sa.Column("projection_version", sa.Text(), nullable=False),
        sa.Column("duty_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("adjustment_score", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_score", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_score_projection_quarter_total_quarter_start",
        "score_projection_quarter_total",
        ["quarter_start"],
    )

    op.create_table(
        "score_projection_state",
        sa.Column(
            "projection_key",
            sa.Text(),
            primary_key=True,
            nullable=False,
            server_default=sa.text("'score_projection'"),
        ),
        sa.Column("canonical_version", sa.Text(), nullable=False),
        sa.Column(
            "backfill_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "resume_after_soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO score_projection_state (
                projection_key,
                canonical_version,
                backfill_complete
            )
            VALUES ('score_projection', '1', false)
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("score_projection_state")
    op.drop_index(
        "ix_score_projection_quarter_total_quarter_start",
        table_name="score_projection_quarter_total",
    )
    op.drop_table("score_projection_quarter_total")
    op.drop_index(
        "ix_soldier_quarter_score_projection_soldier_quarter",
        table_name="soldier_quarter_score_projection",
    )
    op.drop_index(
        "ix_soldier_quarter_score_projection_quarter_start",
        table_name="soldier_quarter_score_projection",
    )
    op.drop_index(
        "ix_soldier_quarter_score_projection_soldier_id",
        table_name="soldier_quarter_score_projection",
    )
    op.drop_table("soldier_quarter_score_projection")
    op.drop_table("soldier_score_projection")
