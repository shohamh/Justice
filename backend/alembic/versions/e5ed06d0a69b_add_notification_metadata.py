"""add_notification_metadata

Revision ID: e5ed06d0a69b
Revises: 5abac7d1ec0b
Create Date: 2026-08-10 10:24:58.444128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5ed06d0a69b'
down_revision: Union[str, Sequence[str], None] = '5abac7d1ec0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "metadata")
