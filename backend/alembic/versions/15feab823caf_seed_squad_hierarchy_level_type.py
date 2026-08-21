"""seed squad hierarchy level type

Revision ID: 15feab823caf
Revises: c7e8f9a0b1c2
Create Date: 2026-08-20 13:24:10.810110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15feab823caf'
down_revision: Union[str, Sequence[str], None] = 'c7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a default "חוליה" (squad) level, one rank below the current lowest
    level. Guarded so it's a no-op if a level with this key already exists
    (e.g. an admin already added one by hand)."""
    op.execute(
        """
        INSERT INTO hierarchy_level_types (id, key, label, rank)
        SELECT gen_random_uuid(), 'squad', 'חוליה', COALESCE(MAX(rank), 0) + 1
        FROM hierarchy_level_types
        -- HAVING (not WHERE) so the guard applies to the single aggregate
        -- row itself: WHERE NOT EXISTS would filter input rows before
        -- aggregation, and MAX() over zero rows still yields one output row
        -- (NULL), which would insert a duplicate 'squad' key anyway.
        HAVING NOT EXISTS (
            SELECT 1 FROM hierarchy_level_types WHERE key = 'squad'
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM hierarchy_level_types WHERE key = 'squad'")
