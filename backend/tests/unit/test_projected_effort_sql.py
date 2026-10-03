from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.models import (
    ScoreAdjustment,
    ScoreProjectionQuarterTotal,
    SoldierQuarterScoreProjection,
)
from app.services import score_projection, scoring
from app.services.effort_score import _compute_effort_data
from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION
from tests.helpers import create_soldier


def test_projected_effort_aggregates_one_result_per_soldier_without_quarter_maps(
    admin_session, monkeypatch
):
    soldiers = [
        create_soldier(admin_session, personal_number=f"890200{i}") for i in range(4)
    ]
    for soldier in soldiers:
        soldier.enrolled_at = date(2026, 1, 1)
    soldiers[1].unit_join_date = date(2026, 5, 15)
    admin_session.flush()

    q1, q2, q3 = date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1)
    windows = [
        (q1, date(2026, 3, 31), q1),
        (q2, date(2026, 6, 30), q2),
        (q3, date(2026, 9, 30), q3),
    ]
    for quarter, total in ((q1, "20"), (q2, "15"), (q3, "0")):
        admin_session.add(
            ScoreProjectionQuarterTotal(
                quarter_start=quarter,
                projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                effective_weighted_days=Decimal("0"),
                duty_score=Decimal("14") if quarter == q2 else Decimal(total),
                adjustment_score=Decimal("1") if quarter == q2 else Decimal("0"),
                total_score=Decimal(total),
            )
        )
    scores = [
        (0, q1, "10", "0"),
        (2, q1, "10", "0"),
        (0, q2, "4", "1"),
        (1, q2, "5", "0"),
        (2, q2, "5", "0"),
    ]
    for index, quarter, duty, adjustment in scores:
        admin_session.add(
            SoldierQuarterScoreProjection(
                soldier_id=soldiers[index].id,
                quarter_start=quarter,
                duty_type_id=None,
                projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                effective_weighted_days=Decimal("0"),
                duty_score=Decimal(duty),
                adjustment_score=Decimal(adjustment),
                source_fingerprint={},
            )
        )
    adjustment = ScoreAdjustment(
        soldier_id=soldiers[0].id, delta=Decimal("1"), reason="projected effort test"
    )
    admin_session.add(adjustment)
    admin_session.flush()
    adjustment.created_at = datetime(2026, 5, 10, tzinfo=UTC)
    admin_session.flush()

    reset_date = q1
    monkeypatch.setattr(scoring, "_burden_share_reset_date", lambda _session: reset_date)
    monkeypatch.setattr(scoring, "_burden_share_quarter_windows", lambda *_args, **_kwargs: windows)
    monkeypatch.setattr(scoring, "_ensure_projection_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        scoring,
        "resolve_reset_dates_for_soldiers",
        lambda _session, _soldiers: {soldier.id: reset_date for soldier in soldiers},
    )
    projection_inputs = scoring._projection_burden_share_inputs(
        admin_session,
        soldiers=soldiers,
        reset_date=reset_date,
        planning_start=date(2026, 10, 1),
        planning_end=date(2026, 10, 1),
    )
    assert projection_inputs is not None
    old_windows, quarter_totals, quarter_scores = projection_inputs
    reference = _compute_effort_data(
        soldiers=soldiers,
        quarters=[(start, end) for start, end, _quarter in old_windows],
        quarter_unit_scores={
            start: quarter_totals.get(quarter, Decimal("0"))
            for start, _end, quarter in old_windows
        },
        quarter_soldier_scores={
            start: quarter_scores.get(quarter, {})
            for start, _end, quarter in old_windows
        },
        soldier_reset_dates={soldier.id: reset_date for soldier in soldiers},
    )
    assert reference[soldiers[0].id].effort_score == Decimal("15") / Decimal("35")
    assert reference[soldiers[3].id].effort_score == Decimal("0")

    def quarter_maps_are_forbidden(*_args, **_kwargs):
        raise AssertionError("projected transparency must not build per-quarter soldier maps")

    monkeypatch.setattr(scoring, "_projection_burden_share_inputs", quarter_maps_are_forbidden)
    result = scoring._try_projected_effort_data(
        admin_session, soldiers, planning_start=date(2026, 10, 1)
    )

    assert result is not None
    assert result.keys() == reference.keys()
    for soldier_id, expected in reference.items():
        actual = result[soldier_id]
        assert abs(actual.effort_score - expected.effort_score) < Decimal("1e-20")
        assert abs(actual.C_over_D - expected.C_over_D) < Decimal("1e-20")
        assert actual.effort_offset == expected.effort_offset
    assert result[soldiers[0].id].effort_score == result[soldiers[2].id].effort_score
    assert result[soldiers[3].id].effort_score == Decimal("0")


def test_projected_effort_keeps_reset_override_fallback(admin_session, monkeypatch):
    soldier = create_soldier(admin_session, personal_number="8902010")
    monkeypatch.setattr(scoring, "_burden_share_reset_date", lambda _session: date(2026, 1, 1))
    monkeypatch.setattr(
        scoring,
        "resolve_reset_dates_for_soldiers",
        lambda _session, _soldiers: {soldier.id: date(2026, 4, 1)},
    )
    assert scoring._try_projected_effort_data(
        admin_session, [soldier], planning_start=date(2026, 10, 1)
    ) is None


def test_projected_effort_keeps_incomplete_projection_fallback(admin_session, monkeypatch):
    soldier = create_soldier(admin_session, personal_number="8902011")
    q1 = date(2026, 1, 1)
    monkeypatch.setattr(scoring, "_burden_share_reset_date", lambda _session: q1)
    monkeypatch.setattr(
        scoring,
        "resolve_reset_dates_for_soldiers",
        lambda _session, _soldiers: {soldier.id: q1},
    )
    monkeypatch.setattr(
        scoring,
        "_burden_share_quarter_windows",
        lambda *_args, **_kwargs: [(q1, date(2026, 3, 31), q1)],
    )
    monkeypatch.setattr(scoring, "_projection_data_keys_for_soldiers", lambda *_args: set())
    monkeypatch.setattr(scoring, "_ensure_projection_ready", lambda *_args, **_kwargs: False)
    assert scoring._try_projected_effort_data(
        admin_session, [soldier], planning_start=date(2026, 4, 1)
    ) is None


def test_projected_effort_rechecks_prevalidated_marker_scope_before_sql(admin_session, monkeypatch):
    soldier = create_soldier(admin_session, personal_number="8902012")
    q1 = date(2026, 1, 1)
    monkeypatch.setattr(scoring, "_burden_share_reset_date", lambda _session: q1)
    monkeypatch.setattr(
        scoring,
        "resolve_reset_dates_for_soldiers",
        lambda _session, _soldiers: {soldier.id: q1},
    )
    monkeypatch.setattr(
        scoring,
        "_burden_share_quarter_windows",
        lambda *_args, **_kwargs: [(q1, date(2026, 3, 31), q1)],
    )
    readiness = scoring._TransparencyProjectionReadiness(
        soldier_ids=frozenset({soldier.id}),
        validated_quarter_starts=frozenset({q1}),
        effort_quarter_starts=frozenset({q1}),
        total_soldier_ids=frozenset({soldier.id}),
    )
    marker_checks = []

    def reject_pending_marker(_session, *, soldier_ids):
        marker_checks.append(frozenset(soldier_ids))
        return True

    monkeypatch.setattr(
        scoring,
        "_ensure_projection_ready",
        lambda *_args, **_kwargs: pytest.fail("prevalidated read repeated full readiness"),
    )
    monkeypatch.setattr(
        score_projection, "projection_has_pending_markers", reject_pending_marker
    )
    monkeypatch.setattr(
        scoring,
        "_projected_effort_data_sql",
        lambda *_args, **_kwargs: pytest.fail("pending marker reached projected read"),
    )
    assert scoring._try_projected_effort_data(
        admin_session,
        [soldier],
        prevalidated_readiness=readiness,
        planning_start=date(2026, 4, 1),
    ) is None
    assert marker_checks == [frozenset({soldier.id})]
