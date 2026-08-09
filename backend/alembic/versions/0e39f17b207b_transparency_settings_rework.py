"""transparency settings rework

Revision ID: 0e39f17b207b
Revises: 5abac7d1ec0b
Create Date: 2026-08-09 20:23:22.291362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e39f17b207b'
down_revision: Union[str, Sequence[str], None] = '5abac7d1ec0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    old = conn.execute(
        sa.text("SELECT value FROM system_settings WHERE key = 'transparency.visible_commander_levels'")
    ).scalar()

    if old:
        # old value is a JSON array of level keys; migrate to the single most
        # senior (lowest-rank) level among them.
        ranks = conn.execute(
            sa.text(
                "SELECT key, rank FROM hierarchy_level_types WHERE key = ANY(:keys)"
            ),
            {"keys": list(old)},
        ).all()
        min_level = min(ranks, key=lambda r: r.rank).key if ranks else "מדור"
    else:
        min_level = "מדור"

    conn.execute(
        sa.text(
            "INSERT INTO system_settings (key, value) VALUES ('transparency.min_visible_level', :v)"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"v": f'"{min_level}"'},
    )
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.visible_commander_levels'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.min_visible_level'"))
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.commander_levels_above'"))
    conn.execute(sa.text("DELETE FROM system_settings WHERE key = 'transparency.duty_manager_levels_above'"))
