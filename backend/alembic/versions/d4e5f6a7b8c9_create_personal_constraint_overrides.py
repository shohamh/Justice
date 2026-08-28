"""create personal_constraint_overrides

Revision ID: d4e5f6a7b8c9
Revises: 366b35d4cff5
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "366b35d4cff5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_constraint_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "personal_constraint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("personal_constraints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "overridden_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assignment_kind", sa.Text(), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "overridden_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_pco_constraint", "personal_constraint_overrides", ["personal_constraint_id"]
    )
    op.create_index("idx_pco_soldier", "personal_constraint_overrides", ["soldier_id"])


def downgrade() -> None:
    op.drop_index("idx_pco_soldier", table_name="personal_constraint_overrides")
    op.drop_index("idx_pco_constraint", table_name="personal_constraint_overrides")
    op.drop_table("personal_constraint_overrides")
