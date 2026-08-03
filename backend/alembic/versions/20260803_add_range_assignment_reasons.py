"""add range assignment reasons

Revision ID: 20260803rar1
Revises: 20260802rq01
Create Date: 2026-08-03 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


revision = "20260803rar1"
down_revision = "20260802rq01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("range_assignments", sa.Column("assignment_reason_code", sa.Text(), nullable=True))
    op.add_column("range_assignments", sa.Column("assignment_reason_text", sa.Text(), nullable=True))
    op.execute(
        "UPDATE range_assignments SET assignment_reason_code = 'legacy', "
        "assignment_reason_text = 'שיבוץ קיים' "
        "WHERE assignment_reason_code IS NULL"
    )


def downgrade() -> None:
    op.drop_column("range_assignments", "assignment_reason_text")
    op.drop_column("range_assignments", "assignment_reason_code")
