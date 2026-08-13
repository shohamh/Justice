"""fix rank advancement interval id to use uuid

Revision ID: 92afb4359c3b
Revises: db05bb8f7744
Create Date: 2026-08-13 23:23:46.399237

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92afb4359c3b'
down_revision: Union[str, Sequence[str], None] = 'db05bb8f7744'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - change id from Integer to UUID."""
    # Drop the old id column and create a new one with UUID type
    # Since this is a new table, we can safely recreate it
    op.execute("ALTER TABLE rank_advancement_intervals DROP COLUMN id CASCADE")
    op.add_column(
        "rank_advancement_intervals",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema - revert id back to Integer."""
    # Revert back to Integer id (though this loses any UUID values)
    op.execute("ALTER TABLE rank_advancement_intervals DROP COLUMN id CASCADE")
    op.add_column(
        "rank_advancement_intervals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    )
