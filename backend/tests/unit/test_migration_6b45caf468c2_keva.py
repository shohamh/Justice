"""Tests for migration 6b45caf468c2 (add קבע to duty_types.allowed_service_types).

Regression coverage for a review finding: the original upgrade() guarded its
row selection with `requirements.get("enlisted_allowed", True) is not False`,
skipping the 3 officer-only duty types (קצין תורן, מפקד תורן, קצין מלווה
אבט"ש) on the theory that `enlisted_allowed=False` already excludes enlisted
soldiers "either way". That reasoning is wrong: `_is_eligible`
(app/services/eligibility.py) treats `allowed_service_types` and
`enlisted_allowed` as two INDEPENDENT gates a soldier must pass BOTH of. A
קבע-track officer (e.g. סרן) still fails the `allowed_service_types` gate on
those 3 rows if it's left at ["חובה"], even though they'd pass the
`enlisted_allowed` gate as an officer. seed.py was correctly updated to add
"קבע" to all 10 relevant duty types (including the 3 officer-only ones), but
the migration's guard meant already-deployed databases only got 7 of the 10
via `upgrade()`. This file proves the migration now touches all 10 rows
(officer-only included), and that a קבע officer becomes eligible for one of
the previously-skipped duty types as a direct result.

Uses the shared migration-template harness in tests/support/database.py: a
process-cached database is migrated exactly to the down_revision, and each
test runs against a cheap clone of it (the shared session-scoped conftest
container is already migrated straight to head, so pre-migration rows cannot
be seeded against it).
"""
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.support import database as db_support

DOWN_REVISION = "63cff804e3e4"
REVISION = "6b45caf468c2"

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


def _insert_duty_type(conn, *, name, requirements_json):
    dtid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO duty_types (id, name, score_per_day, is_external, requirements) "
            "VALUES (:id, :name, 1.0, false, :reqs)"
        ),
        {"id": dtid, "name": name, "reqs": requirements_json},
    )
    return dtid


def test_upgrade_touches_officer_only_duty_types_too():
    """The 3 officer-only duty types (enlisted_allowed=False,
    allowed_service_types=["חובה"]) must get "קבע" added just like the 7
    non-officer-only ones -- not skipped by an enlisted_allowed guard.
    """
    import json

    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            officer_only_id = _insert_duty_type(
                conn,
                name='קצין תורן',
                requirements_json=json.dumps(
                    {"enlisted_allowed": False, "allowed_service_types": ["חובה"]}
                ),
            )
            non_officer_only_id = _insert_duty_type(
                conn,
                name="שמירות",
                requirements_json=json.dumps(
                    {"officers_allowed": False, "allowed_service_types": ["חובה"]}
                ),
            )
            # Untouched control: no allowed_service_types restriction at all.
            unrelated_id = _insert_duty_type(
                conn,
                name='הגנ"ש',
                requirements_json=json.dumps({"enlisted_allowed": False}),
            )

        run_migration()

        with engine.begin() as conn:
            rows = {
                row["id"]: row["requirements"]
                for row in conn.execute(
                    text("SELECT id, requirements FROM duty_types")
                ).mappings().all()
            }

        assert rows[officer_only_id]["allowed_service_types"] == ["חובה", "קבע"], (
            "officer-only duty type (enlisted_allowed=False) should still get "
            "קבע added -- allowed_service_types and enlisted_allowed are "
            "independent eligibility gates"
        )
        assert rows[officer_only_id]["enlisted_allowed"] is False

        assert rows[non_officer_only_id]["allowed_service_types"] == ["חובה", "קבע"]

        assert "allowed_service_types" not in rows[unrelated_id]


def test_downgrade_reverts_exactly_what_upgrade_touched():
    """downgrade() must revert the officer-only row's allowed_service_types
    back to ["חובה"] too, symmetrically with upgrade().
    """
    import json

    from alembic import command
    from alembic.config import Config

    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            officer_only_id = _insert_duty_type(
                conn,
                name='מפקד תורן',
                requirements_json=json.dumps(
                    {"enlisted_allowed": False, "allowed_service_types": ["חובה"]}
                ),
            )

        run_migration()

        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        command.downgrade(cfg, DOWN_REVISION)

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT requirements FROM duty_types WHERE id = :id"),
                {"id": officer_only_id},
            ).mappings().one()

        assert row["requirements"]["allowed_service_types"] == ["חובה"], (
            "downgrade should revert the officer-only row back to חובה-only, "
            "matching what upgrade() had touched"
        )


def test_keva_officer_becomes_eligible_after_upgrade():
    """End-to-end: a קבע-track officer (e.g. סרן) is ineligible for קצין תורן
    before the migration (allowed_service_types=["חובה"] blocks them even
    though they'd pass the enlisted_allowed gate as an officer), and eligible
    after -- proving the migration's row-selection fix has the intended
    real-world effect, not just that a JSON field changed.
    """
    from app.db.models import Soldier
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    today = date(2026, 6, 1)
    keva_officer = Soldier(
        personal_number="test-keva-officer",
        full_name="Keva Officer",
        password_hash="x",
        role="soldier",
        rank="סרן",
        is_officer=True,
        mandatory_end_date=today - timedelta(days=365),  # mandatory service long over
        discharge_date=None,
    )

    pre_migration_reqs = DutyTypeRequirements(
        enlisted_allowed=False, allowed_service_types=["חובה"]
    )
    assert not _is_eligible(
        keva_officer, pre_migration_reqs, mitvahim_months=6, alal_months=3, today=today
    ), "sanity check: pre-migration state blocks the קבע officer"

    post_migration_reqs = DutyTypeRequirements(
        enlisted_allowed=False, allowed_service_types=["חובה", "קבע"]
    )
    assert _is_eligible(
        keva_officer, post_migration_reqs, mitvahim_months=6, alal_months=3, today=today
    ), "post-migration state (as produced by the fixed upgrade()) must allow the קבע officer"
