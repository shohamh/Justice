"""create exemption_requests table

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, Sequence[str], None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exemption_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exemption_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_exemption_requests_soldier"
        ),
        sa.ForeignKeyConstraint(
            ["exemption_type_id"],
            ["exemption_types.id"],
            ondelete="RESTRICT",
            name="fk_exemption_requests_type",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["soldiers.id"],
            ondelete="SET NULL",
            name="fk_exemption_requests_decided_by",
        ),
    )
    op.create_index(
        "ix_exemption_requests_soldier_id",
        "exemption_requests",
        ["soldier_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_exemption_requests_soldier_id", table_name="exemption_requests")
    op.drop_table("exemption_requests")
