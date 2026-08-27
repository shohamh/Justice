"""fix Hebrew-label level-key settings to seeded English keys

Revision ID: 366b35d4cff5
Revises: d8e9f0a1b2c3
Create Date: 2026-08-27 09:03:46.499657

Several system_settings values, and one hardcoded fallback, were seeded with
the Hebrew *label* of a hierarchy level ("מדור", "ענף") instead of the
seeded *key* ("group", "branch") that get_level_rank() actually matches
against (HierarchyLevelType.key, not .label — see
alembic/versions/0059_hierarchy_level_types.py). A label never matches any
row, so the rank lookup silently resolved to None and every level-threshold
check using one of these settings treated that as an unconditional denial,
regardless of the actor's real level.

Only rows still holding the original broken default are updated — a
deployment where an admin already reconfigured one of these settings to a
real (even if different) key is left untouched, since that's a deliberate
choice, not the bug this migration corrects.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '366b35d4cff5'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE system_settings SET value = '\"branch\"' "
        "WHERE key = 'mitvachim.attendance_edit_min_level' AND value = '\"ענף\"'"
    )
    op.execute(
        "UPDATE system_settings SET value = '\"group\"' "
        "WHERE key = 'mitvachim.excusal_approve_min_commander_level' AND value = '\"מדור\"'"
    )
    op.execute(
        "UPDATE system_settings SET value = '\"group\"' "
        "WHERE key = 'transparency.min_visible_level' AND value = '\"מדור\"'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE system_settings SET value = '\"ענף\"' "
        "WHERE key = 'mitvachim.attendance_edit_min_level' AND value = '\"branch\"'"
    )
    op.execute(
        "UPDATE system_settings SET value = '\"מדור\"' "
        "WHERE key = 'mitvachim.excusal_approve_min_commander_level' AND value = '\"group\"'"
    )
    op.execute(
        "UPDATE system_settings SET value = '\"מדור\"' "
        "WHERE key = 'transparency.min_visible_level' AND value = '\"group\"'"
    )
