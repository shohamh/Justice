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
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    # Explicitly create the primary key constraint (ADD COLUMN with primary_key=True
    # doesn't create the constraint in Postgres; it only works with CREATE TABLE)
    op.create_primary_key("rank_advancement_intervals_pkey", "rank_advancement_intervals", ["id"])


def downgrade() -> None:
    """Downgrade schema - revert id back to Integer."""
    # Drop the primary key constraint first
    op.drop_constraint("rank_advancement_intervals_pkey", "rank_advancement_intervals", type_="pk")
    # Revert back to Integer id (though this loses any UUID values)
    op.execute("ALTER TABLE rank_advancement_intervals DROP COLUMN id CASCADE")
    op.add_column(
        "rank_advancement_intervals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    )
    # Explicitly create the primary key constraint for the Integer id
    op.create_primary_key("rank_advancement_intervals_pkey", "rank_advancement_intervals", ["id"])
