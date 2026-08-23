from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services.score_projection import (
    SCORE_PROJECTION_CANONICAL_VERSION,
    SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
    _get_or_create_state,
    commander_score_totals,
    rebuild_projection_bucket,
)
from app.services.tests.test_score_projection import _seed_projection_scenario
from app.services.settings_loader import set_setting
from tests.helpers import create_soldier


def _seed_commander_score_history(admin_session):
    soldier = create_soldier(admin_session, personal_number="score-observability-01")
    duty_type = DutyType(name="score-observability-duty", score_per_day=Decimal("2.50"))
    location = DutyLocation(name="score-observability-location")
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            status="published",
        )
    )
    admin_session.flush()
    return soldier


def _enable_commander_projection_rollout(admin_session, *, backfill_complete: bool) -> None:
    set_setting(
        admin_session,
        SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
        True,
        actor_id=None,
    )
    state = _get_or_create_state(admin_session)
    state.backfill_complete = backfill_complete
    state.canonical_version = SCORE_PROJECTION_CANONICAL_VERSION
    admin_session.flush()


def test_commander_score_totals_fall_back_until_projection_backfill_is_complete(admin_session):
    soldier = _seed_commander_score_history(admin_session)
    _enable_commander_projection_rollout(admin_session, backfill_complete=False)
    admin_session.add(
        SoldierScoreProjection(
            soldier_id=soldier.id,
            projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
            duty_score=Decimal("0.000000"),
            adjustment_score=Decimal("0.000000"),
            cumulative_score=Decimal("0.000000"),
            shift_count=0,
        )
    )
    admin_session.flush()

    result = commander_score_totals(
        admin_session,
        soldiers=[soldier],
        canonical_diagnostic_compare=True,
    )

    assert result.score_by_soldier[soldier.id] == Decimal("7.500000")
    assert result.diagnostics.gate_enabled is True
    assert result.diagnostics.used_projection is False
    assert result.diagnostics.fallback_reason == "projection_backfill_incomplete"


def test_commander_score_totals_report_matching_dual_read_when_projection_matches(admin_session):
    soldier = _seed_commander_score_history(admin_session)
    target_quarter = date(2026, 7, 1)
    rebuild_projection_bucket(admin_session, soldier.id, target_quarter)
    _enable_commander_projection_rollout(admin_session, backfill_complete=True)

    result = commander_score_totals(
        admin_session,
        soldiers=[soldier],
        canonical_diagnostic_compare=True,
    )

    assert result.score_by_soldier[soldier.id] == Decimal("7.500000")
    assert result.diagnostics.used_projection is True
    assert result.diagnostics.compared_soldiers == 1
    assert result.diagnostics.matched_soldiers == 1
    assert result.diagnostics.repaired_soldiers == 0
    assert result.diagnostics.divergent_soldiers == 0
    assert result.diagnostics.fallback_reason is None


def test_commander_score_totals_repair_divergent_projection_before_returning(admin_session):
    soldier = _seed_commander_score_history(admin_session)
    target_quarter = date(2026, 7, 1)
    rebuild_projection_bucket(admin_session, soldier.id, target_quarter)
    _enable_commander_projection_rollout(admin_session, backfill_complete=True)

    broken_row = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier.id,
            SoldierQuarterScoreProjection.quarter_start == target_quarter,
            SoldierQuarterScoreProjection.duty_type_id.is_not(None),
        )
    ).scalar_one()
    broken_row.duty_score = Decimal("0.000000")
    broken_total = admin_session.get(SoldierScoreProjection, soldier.id)
    assert broken_total is not None
    broken_total.duty_score = Decimal("0.000000")
    broken_total.cumulative_score = Decimal("0.000000")
    broken_total.shift_count = 0
    admin_session.flush()

    result = commander_score_totals(
        admin_session,
        soldiers=[soldier],
        canonical_diagnostic_compare=True,
    )

    repaired_total = admin_session.get(SoldierScoreProjection, soldier.id)
    repaired_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier.id,
            SoldierQuarterScoreProjection.quarter_start == target_quarter,
        )
    ).scalars().all()

    assert result.score_by_soldier[soldier.id] == Decimal("7.500000")
    assert result.diagnostics.used_projection is True
    assert result.diagnostics.repaired_soldiers == 1
    assert result.diagnostics.divergent_soldiers == 0
    assert repaired_total is not None
    assert repaired_total.cumulative_score == Decimal("7.500000")
    assert sum((row.duty_score + row.adjustment_score for row in repaired_rows), Decimal("0")) == Decimal(
        "7.500000"
    )


def test_commander_score_totals_use_authoritative_projection_for_override_reserve_and_dismissal_history(
    admin_session,
):
    scenario = _seed_projection_scenario(admin_session)
    rebuild_projection_bucket(admin_session, scenario["primary"].id, scenario["q2"])
    rebuild_projection_bucket(admin_session, scenario["primary"].id, scenario["q3"])
    rebuild_projection_bucket(admin_session, scenario["replacement"].id, scenario["q2"])
    _enable_commander_projection_rollout(admin_session, backfill_complete=True)

    result = commander_score_totals(
        admin_session,
        soldiers=[scenario["primary"], scenario["replacement"]],
    )

    assert result.score_by_soldier[scenario["primary"].id] == Decimal("8.700000")
    assert result.score_by_soldier[scenario["replacement"].id] == Decimal("0.500000")
    assert result.diagnostics.used_projection is True
    assert result.diagnostics.compared_soldiers == 0
    assert result.diagnostics.matched_soldiers == 0
    assert result.diagnostics.divergent_soldiers == 0
    assert result.diagnostics.fallback_reason is None
