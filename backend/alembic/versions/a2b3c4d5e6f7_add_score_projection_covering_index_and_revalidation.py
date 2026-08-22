"""add score projection covering index and revalidation cursor

Revision ID: a2b3c4d5e6f7
Revises: 9b1c2d3e4f5a
Create Date: 2026-08-22 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "9b1c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Covering index so the read-path completeness check (row counts and
    # projection versions per bucket) is an index-only scan and never touches
    # the wide heap rows that carry the JSONB fingerprints.
    op.create_index(
        "ix_sqsp_soldier_quarter_cover",
        "soldier_quarter_score_projection",
        ["soldier_id", "quarter_start"],
        unique=False,
        postgresql_include=["duty_type_id", "projection_version"],
    )
    # Keyset-pagination cursor for the periodic fingerprint revalidation
    # worker; NULL means the next cycle starts from the beginning.
    op.add_column(
        "score_projection_state",
        sa.Column(
            "revalidated_after_soldier_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "score_projection_state",
        sa.Column("revalidated_after_quarter_start", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("score_projection_state", "revalidated_after_quarter_start")
    op.drop_column("score_projection_state", "revalidated_after_soldier_id")
    op.drop_index("ix_sqsp_soldier_quarter_cover", table_name="soldier_quarter_score_projection")
