from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text

from app.db.models import ScoreProjectionDirtyBucket, SoldierScoreProjection
from app.services import score_projection, scoring
from app.services.tests.test_projected_scoring_reads import (
    _build_projected_scenario,
    _completed_backfill,
)


def _prepared_totals(session):
    scenario, _admin = _build_projected_scenario(session)
    _completed_backfill(session)
    session.flush()
    return scenario


def _marker(session, *, soldier_id, quarter_start):
    marker = session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == soldier_id,
            ScoreProjectionDirtyBucket.quarter_start == quarter_start,
        )
    ).scalar_one_or_none()
    if marker is None:
        marker = ScoreProjectionDirtyBucket(
            soldier_id=soldier_id, quarter_start=quarter_start, status="current"
        )
        session.add(marker)
        session.flush()
    return marker


def test_clean_required_totals_do_not_hydrate_projection_rows(admin_session, monkeypatch):
    scenario = _prepared_totals(admin_session)
    soldier_ids = {scenario["primary"].id, scenario["replacement"].id}

    def reject_hydration(*_args, **_kwargs):
        raise AssertionError("healthy totals should not be hydrated")

    monkeypatch.setattr(scoring, "_soldier_totals_by_id", reject_hydration)
    assert scoring._refresh_required_soldier_totals(admin_session, soldier_ids=soldier_ids)


def test_jsonb_null_marker_is_cleared_for_soldier_total_refresh(admin_session, monkeypatch):
    scenario = _prepared_totals(admin_session)
    soldier_id = scenario["primary"].id
    quarter_start = scenario["q3"]
    _marker(admin_session, soldier_id=soldier_id, quarter_start=quarter_start)
    admin_session.execute(
        text(
            "UPDATE score_projection_dirty_buckets "
            "SET status = 'current', divergence = 'null'::jsonb, reconciled_at = NULL "
            "WHERE soldier_id = :soldier_id AND quarter_start = :quarter_start"
        ),
        {"soldier_id": soldier_id, "quarter_start": quarter_start},
    )

    def reject_recalculation(*_args, **_kwargs):
        raise AssertionError("cleared JSONB null should not trigger recalculation")

    monkeypatch.setattr(score_projection, "_expected_soldier_totals_by_id", reject_recalculation)
    assert scoring._refresh_required_soldier_totals(admin_session, soldier_ids={soldier_id})


@pytest.mark.parametrize("marker_state", ["dirty", "divergent"])
def test_pending_marker_repairs_implicated_total(admin_session, marker_state):
    scenario = _prepared_totals(admin_session)
    soldier_id = scenario["primary"].id
    row = admin_session.get(SoldierScoreProjection, soldier_id)
    correct_score = row.cumulative_score
    row.cumulative_score = Decimal("999.000000")
    marker = _marker(admin_session, soldier_id=soldier_id, quarter_start=scenario["q3"])
    marker.status = "dirty" if marker_state == "dirty" else "current"
    marker.divergence = {"pending": True} if marker_state == "divergent" else None
    marker.reconciled_at = None
    admin_session.flush()

    assert scoring._refresh_required_soldier_totals(admin_session, soldier_ids={soldier_id})
    assert row.cumulative_score == correct_score


def test_reconciled_divergence_does_not_repair_soldier_total(admin_session, monkeypatch):
    scenario = _prepared_totals(admin_session)
    soldier_id = scenario["primary"].id
    marker = _marker(admin_session, soldier_id=soldier_id, quarter_start=scenario["q3"])
    marker.status = "current"
    marker.divergence = {"before": "recorded"}
    marker.reconciled_at = datetime.now(UTC)
    admin_session.flush()

    def reject_recalculation(*_args, **_kwargs):
        raise AssertionError("reconciled audit row should not trigger recalculation")

    monkeypatch.setattr(score_projection, "_expected_soldier_totals_by_id", reject_recalculation)
    assert scoring._refresh_required_soldier_totals(admin_session, soldier_ids={soldier_id})


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_stale_total_only_hydrates_flagged_soldier(admin_session, monkeypatch, missing):
    scenario = _prepared_totals(admin_session)
    soldier_id = scenario["primary"].id
    healthy_id = scenario["replacement"].id
    if missing:
        admin_session.execute(
            delete(SoldierScoreProjection).where(SoldierScoreProjection.soldier_id == soldier_id)
        )
    else:
        admin_session.get(SoldierScoreProjection, soldier_id).projection_version = "stale"
    admin_session.flush()

    hydrated_ids = []
    original_hydrate = scoring._soldier_totals_by_id

    def record_hydration(session, soldier_ids):
        hydrated_ids.append(set(soldier_ids))
        return original_hydrate(session, soldier_ids)

    monkeypatch.setattr(scoring, "_soldier_totals_by_id", record_hydration)
    assert scoring._refresh_required_soldier_totals(
        admin_session, soldier_ids={soldier_id, healthy_id}
    )
    assert hydrated_ids
    assert all(ids == {soldier_id} for ids in hydrated_ids)
    repaired = admin_session.get(SoldierScoreProjection, soldier_id)
    assert repaired is not None
    assert repaired.projection_version == score_projection.SCORE_PROJECTION_CANONICAL_VERSION
