"""Regression coverage for the hierarchy-transfer reason migration."""

from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.support import database as db_support

pytestmark = pytest.mark.slow

DOWN_REVISION = "20260829rar1"
REVISION = "20260829_transfer_reason"
_TEMPLATE = None


@contextmanager
def _db_at_down_revision():
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = db_support.get_migrated_template(
            DOWN_REVISION, Path(__file__).resolve().parents[2]
        )
    with db_support.cloned_migration_database(
        _TEMPLATE,
        upgrade_to_revision=REVISION,
        rootpath=Path(__file__).resolve().parents[2],
    ) as (engine, run_migration):
        yield engine, run_migration


def test_upgrade_adds_hierarchy_transfer_reason_column():
    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            before = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'hierarchy_transfer_requests'
                      AND column_name = 'reason'
                    """
                )
            ).first()
        assert before is None

        run_migration()

        with engine.begin() as conn:
            after = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'hierarchy_transfer_requests'
                      AND column_name = 'reason'
                    """
                )
            ).first()
        assert after is not None
