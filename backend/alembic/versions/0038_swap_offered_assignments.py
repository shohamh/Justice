"""add offered_assignment_ids to swap_requests

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "swap_requests",
        sa.Column(
            "offered_assignment_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("swap_requests", "offered_assignment_ids")
