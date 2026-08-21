from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.db.models import SoldierQuarterScoreProjection
from app.services import effort_score, scoring
from app.services.effort_score import compute_effort_breakdown
from app.services.score_projection import backfill_score_projection
from app.services.tests.test_score_projection import _seed_projection_scenario
from tests.helpers import create_soldier


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.000001"))
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _canonical_breakdown(breakdown) -> dict[str, Any]:
    return _canonical(
        {
            "quarters": [
                {
                    "quarter_start": quarter.quarter_start,
                    "quarter_end": quarter.quarter_end,
                    "quarter_label": quarter.quarter_label,
                    "soldier_score": quarter.soldier_score,
                    "unit_score": quarter.unit_score,
                    "active_frac": quarter.active_frac,
                    "share": quarter.share,
                    "weighted_share": quarter.weighted_share,
                    "is_partial": quarter.is_partial,
                    "adjustment_delta": quarter.adjustment_delta,
                }
                for quarter in breakdown.quarters
            ],
            "effort_score": breakdown.effort_score,
            "A_i": breakdown.A_i,
            "W_i": breakdown.W_i,
        }
    )


def _build_projected_scenario(session):
    scenario = _seed_projection_scenario(session)
    admin = create_soldier(
        session,
        personal_number="projected-read-admin",
        role="admin",
        full_name="Projected Read Admin",
    )
    return scenario, admin


def _fail_if_expands_duty_days(*_args, **_kwargs):
    raise AssertionError("normal projected scoring read expanded duty days")


def test_transparency_rows_match_legacy_from_projection_without_expanding_duty_days(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    backfill_score_projection(admin_session)
    admin_session.flush()

    monkeypatch.setattr(scoring, "_effective_duty_day_rows", _fail_if_expands_duty_days)

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    assert projected["rows"]
    assert [set(row) for row in projected["rows"]] == [set(row) for row in legacy["rows"]]
    assert _canonical(projected) == _canonical(legacy)
    primary = next(row for row in projected["rows"] if row["soldier_id"] == scenario["primary"].id)
    assert primary["shift_count"] == 2
    assert primary["cumulative_score"] == Decimal("8.700000")


def test_fairness_components_use_projected_effort_without_calling_transparency_rows(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    _scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.fairness_components(admin_session, viewer=admin)
    backfill_score_projection(admin_session)
    admin_session.flush()

    def fail_transparency(*_args, **_kwargs):
        raise AssertionError("fairness must not call transparency_rows")

    monkeypatch.setattr(scoring, "transparency_rows", fail_transparency)

    projected = scoring.fairness_components(admin_session, viewer=admin)

    assert _canonical(projected) == _canonical(legacy)


def test_effort_breakdown_matches_legacy_from_projection_and_keeps_preview_in_memory(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    scenario, _admin = _build_projected_scenario(admin_session)
    soldier = scenario["primary"]
    legacy = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
        extra_adj_delta=Decimal("3.25"),
        extra_adj_date=date(2026, 7, 20),
    )
    backfill_score_projection(admin_session)
    admin_session.flush()

    monkeypatch.setattr(effort_score, "effective_duty_days", _fail_if_expands_duty_days)

    projected = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
        extra_adj_delta=Decimal("3.25"),
        extra_adj_date=date(2026, 7, 20),
    )

    assert _canonical_breakdown(projected) == _canonical_breakdown(legacy)
    q3 = next(quarter for quarter in projected.quarters if quarter.quarter_start == scenario["q3"])
    assert q3.adjustment_delta == Decimal("8.250000")


def test_transparency_rebuilds_missing_projection_bucket_before_serving_projected_read(
    admin_session,
):
    scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    backfill_score_projection(admin_session)
    admin_session.flush()

    admin_session.execute(
        delete(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == scenario["primary"].id,
            SoldierQuarterScoreProjection.quarter_start == scenario["q3"],
        )
    )
    admin_session.flush()

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    rebuilt_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == scenario["primary"].id,
            SoldierQuarterScoreProjection.quarter_start == scenario["q3"],
        )
    ).scalars().all()
    assert rebuilt_rows
    assert _canonical(projected) == _canonical(legacy)
