"""Tests for migration 0e39f17b207b (transparency settings rework)."""
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.support import database as db_support

DOWN_REVISION = "5abac7d1ec0b"
REVISION = "0e39f17b207b"

pytestmark = pytest.mark.slow

_TEMPLATE = None


@contextmanager
def _db_at_down_revision():
    """Fresh clone of the cached template migrated to DOWN_REVISION, plus a
    callable that steps it one more revision (onto REVISION)."""
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = db_support.get_migrated_template(
            DOWN_REVISION, Path(__file__).resolve().parents[2]
        )
    with db_support.cloned_migration_database(
        _TEMPLATE, upgrade_to_revision=REVISION, rootpath=Path(__file__).resolve().parents[2]
    ) as (engine, run_migration):
        yield engine, run_migration


def test_nonempty_old_array_migrates_to_most_senior_level():
    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES "
                "(gen_random_uuid(), 'אגף', 'אגף', 9000), (gen_random_uuid(), 'ענף', 'ענף', 9001)"
            ))
            conn.execute(text(
                "INSERT INTO system_settings (key, value) VALUES "
                "('transparency.visible_commander_levels', '[\"ענף\", \"אגף\"]'::jsonb)"
            ))
        run_migration()
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level'"
            )).scalar()
            old_row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.visible_commander_levels'"
            )).scalar()
        assert row == "אגף"  # rank 9000 is more senior than rank 9001
        assert old_row is None


def test_empty_or_missing_old_value_migrates_to_default_level():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level'"
            )).scalar()
        assert row == "מדור"
