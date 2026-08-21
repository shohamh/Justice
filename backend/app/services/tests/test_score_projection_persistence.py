from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    ScoreProjectionQuarterTotal,
    ScoreProjectionState,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services.score_projection import (
    SCORE_PROJECTION_CANONICAL_VERSION,
    backfill_score_projection,
    rebuild_projection_bucket,
)
from app.services.tests.test_score_projection import _seed_projection_scenario
from tests.helpers import create_soldier


def _quarter_row(session, *, soldier_id, quarter_start_value: date) -> SoldierQuarterScoreProjection:
    return session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id,
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
        )
    ).scalar_one()


def _soldier_total(session, *, soldier_id) -> SoldierScoreProjection:
    return session.execute(
        select(SoldierScoreProjection).where(SoldierScoreProjection.soldier_id == soldier_id)
    ).scalar_one()


def _quarter_total(session, *, quarter_start_value: date) -> ScoreProjectionQuarterTotal:
    return session.execute(
        select(ScoreProjectionQuarterTotal).where(
            ScoreProjectionQuarterTotal.quarter_start == quarter_start_value
        )
    ).scalar_one()


def test_rebuild_projection_bucket_persists_json_safe_fingerprint_and_totals(admin_session):
    scenario = _seed_projection_scenario(admin_session)

    rebuild_projection_bucket(admin_session, scenario["primary"].id, scenario["q3"])
    admin_session.flush()

    persisted_bucket = _quarter_row(
        admin_session, soldier_id=scenario["primary"].id, quarter_start_value=scenario["q3"]
    )
    persisted_total = _soldier_total(admin_session, soldier_id=scenario["primary"].id)
    persisted_quarter_total = _quarter_total(admin_session, quarter_start_value=scenario["q3"])
    state = admin_session.execute(select(ScoreProjectionState)).scalar_one()

    assert persisted_bucket.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert persisted_bucket.duty_score == Decimal("2.70")
    assert persisted_bucket.adjustment_score == Decimal("5.00")
    assert persisted_bucket.total_score == Decimal("7.70")
    assert persisted_bucket.shift_count == 2

    july_first = next(
        row for row in persisted_bucket.source_fingerprint["duty_rows"] if row["day"] == "2026-07-01"
    )
    assert july_first == {
        "assignment_id": str(scenario["cross_quarter"].id),
        "day": "2026-07-01",
        "duty_type_id": str(scenario["cross_quarter"].duty_type_id),
        "assignment_soldier_id": str(scenario["primary"].id),
        "effective_soldier_id": str(scenario["primary"].id),
        "day_weight": "1",
        "multiplier": "0.0",
        "multiplier_source": "dismissal",
        "weighted_multiplier": "0.0",
        "override_id": None,
        "override_date": None,
        "override_effective_soldier_id": None,
        "override_reason": None,
        "dismissal_id": str(scenario["dismissal"].id),
        "dismissed_from": "2026-07-01",
        "dismissed_to": "2026-07-01",
        "dismissal_reason": None,
        "score": "0.000",
    }
    assert persisted_bucket.source_fingerprint["adjustments"] == [
        {
            "adjustment_id": str(scenario["primary_adjustment"].id),
            "delta": "5.00",
            "created_at": "2026-07-15T12:00:00+00:00",
        }
    ]

    assert persisted_total.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert persisted_total.duty_score == Decimal("2.70")
    assert persisted_total.adjustment_score == Decimal("5.00")
    assert persisted_total.cumulative_score == Decimal("7.70")
    assert persisted_total.shift_count == 2

    assert persisted_quarter_total.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert persisted_quarter_total.duty_score == Decimal("2.70")
    assert persisted_quarter_total.adjustment_score == Decimal("5.00")
    assert persisted_quarter_total.total_score == Decimal("7.70")

    assert state.canonical_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert state.backfill_complete is False
    assert state.resume_after_soldier_id is None


def test_rebuild_projection_bucket_replaces_requested_zero_bucket(admin_session):
    soldier = create_soldier(admin_session, personal_number="score-proj-zero")
    target_quarter = date(2026, 10, 1)
    admin_session.add(
        SoldierQuarterScoreProjection(
            soldier_id=soldier.id,
            quarter_start=target_quarter,
            projection_version="stale",
            duty_score=Decimal("9.90"),
            adjustment_score=Decimal("1.10"),
            total_score=Decimal("11.00"),
            shift_count=4,
            source_fingerprint={"legacy": True},
        )
    )
    admin_session.flush()

    rebuild_projection_bucket(admin_session, soldier.id, target_quarter)
    admin_session.flush()

    persisted_bucket = _quarter_row(admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter)
    persisted_total = _soldier_total(admin_session, soldier_id=soldier.id)
    persisted_quarter_total = _quarter_total(admin_session, quarter_start_value=target_quarter)

    assert persisted_bucket.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert persisted_bucket.duty_score == Decimal("0")
    assert persisted_bucket.adjustment_score == Decimal("0")
    assert persisted_bucket.total_score == Decimal("0")
    assert persisted_bucket.shift_count == 0
    assert persisted_bucket.source_fingerprint == {
        "duty_rows": [],
        "overrides": [],
        "dismissals": [],
        "adjustments": [],
    }

    assert persisted_total.cumulative_score == Decimal("0")
    assert persisted_total.shift_count == 0
    assert persisted_quarter_total.total_score == Decimal("0")


def test_backfill_score_projection_is_resumable_and_idempotent(admin_session):
    scenario = _seed_projection_scenario(admin_session)
    idle_soldier = create_soldier(admin_session, personal_number="score-proj-idle")
    all_soldier_ids = sorted(
        [scenario["primary"].id, scenario["replacement"].id, idle_soldier.id], key=str
    )

    first_state = backfill_score_projection(admin_session, batch_size=1)
    admin_session.flush()

    first_rows = admin_session.execute(select(SoldierScoreProjection)).scalars().all()
    assert {row.soldier_id for row in first_rows} == {all_soldier_ids[0]}
    assert first_state.canonical_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert first_state.backfill_complete is False
    assert first_state.resume_after_soldier_id == all_soldier_ids[0]

    finished_state = backfill_score_projection(
        admin_session, batch_size=10, resume_after=first_state.resume_after_soldier_id
    )
    admin_session.flush()

    all_totals = admin_session.execute(
        select(SoldierScoreProjection).order_by(SoldierScoreProjection.soldier_id)
    ).scalars().all()
    all_buckets = admin_session.execute(select(SoldierQuarterScoreProjection)).scalars().all()
    quarter_totals = admin_session.execute(select(ScoreProjectionQuarterTotal)).scalars().all()

    assert [row.soldier_id for row in all_totals] == all_soldier_ids
    assert _soldier_total(admin_session, soldier_id=scenario["primary"].id).cumulative_score == Decimal(
        "8.70"
    )
    assert _soldier_total(admin_session, soldier_id=idle_soldier.id).cumulative_score == Decimal("0")
    assert len(all_buckets) == 3
    assert {row.quarter_start for row in quarter_totals} == {scenario["q2"], scenario["q3"]}

    rerun_state = backfill_score_projection(admin_session, batch_size=10)
    admin_session.flush()

    rerun_buckets = admin_session.execute(select(SoldierQuarterScoreProjection)).scalars().all()
    rerun_totals = admin_session.execute(select(SoldierScoreProjection)).scalars().all()

    assert finished_state.backfill_complete is True
    assert finished_state.resume_after_soldier_id is None
    assert rerun_state.backfill_complete is True
    assert len(rerun_buckets) == len(all_buckets)
    assert len(rerun_totals) == len(all_totals)
    assert len({(row.soldier_id, row.quarter_start) for row in rerun_buckets}) == len(rerun_buckets)


def test_projection_tables_enforce_unique_keys_and_foreign_keys(admin_session):
    scenario = _seed_projection_scenario(admin_session)
    rebuild_projection_bucket(admin_session, scenario["primary"].id, scenario["q3"])
    admin_session.flush()

    with pytest.raises(IntegrityError):
        with admin_session.begin_nested():
            admin_session.add(
                SoldierQuarterScoreProjection(
                    soldier_id=scenario["primary"].id,
                    quarter_start=scenario["q3"],
                    projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                    duty_score=Decimal("0"),
                    adjustment_score=Decimal("0"),
                    total_score=Decimal("0"),
                    shift_count=0,
                    source_fingerprint={},
                )
            )
            admin_session.flush()

    with pytest.raises(IntegrityError):
        with admin_session.begin_nested():
            admin_session.add(
                SoldierScoreProjection(
                    soldier_id=uuid.uuid4(),
                    projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                    duty_score=Decimal("0"),
                    adjustment_score=Decimal("0"),
                    cumulative_score=Decimal("0"),
                    shift_count=0,
                )
            )
            admin_session.flush()
