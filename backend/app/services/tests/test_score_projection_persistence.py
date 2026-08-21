from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    DutyAssignment,
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
from app.services.tests.test_score_projection import (
    _duty_type,
    _location,
    _seed_projection_scenario,
)
from tests.helpers import create_soldier


def _quarter_rows(
    session, *, soldier_id, quarter_start_value: date
) -> list[SoldierQuarterScoreProjection]:
    rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id,
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
        )
    ).scalars().all()
    return sorted(rows, key=lambda row: (row.duty_type_id is None, str(row.duty_type_id or "")))


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


def test_rebuild_projection_bucket_persists_duty_type_rows_and_quarter_aggregate(admin_session):
    scenario = _seed_projection_scenario(admin_session)
    second_type = _duty_type(admin_session, name="score-projection-duty-2", score="2.00")
    second_location = _location(admin_session, name="score-projection-location-2")
    admin_session.add(
        DutyAssignment(
            soldier_id=scenario["primary"].id,
            duty_type_id=second_type.id,
            duty_location_id=second_location.id,
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 22),
            status="published",
        )
    )
    admin_session.flush()

    rebuild_projection_bucket(admin_session, scenario["primary"].id, scenario["q3"])
    admin_session.flush()

    persisted_rows = _quarter_rows(
        admin_session, soldier_id=scenario["primary"].id, quarter_start_value=scenario["q3"]
    )
    persisted_total = _soldier_total(admin_session, soldier_id=scenario["primary"].id)
    persisted_quarter_total = _quarter_total(admin_session, quarter_start_value=scenario["q3"])
    state = admin_session.execute(select(ScoreProjectionState)).scalar_one()

    assert len(persisted_rows) == 3
    rows_by_type = {row.duty_type_id: row for row in persisted_rows}
    main_type_row = rows_by_type[scenario["cross_quarter"].duty_type_id]
    second_type_row = rows_by_type[second_type.id]
    aggregate_row = rows_by_type[None]

    assert main_type_row.duty_type_id == scenario["cross_quarter"].duty_type_id
    assert main_type_row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert main_type_row.raw_day_count == 5
    assert main_type_row.effective_weighted_days == Decimal("2.700000")
    assert main_type_row.duty_score == Decimal("2.700000")
    assert main_type_row.adjustment_score == Decimal("0.000000")
    assert {
        row["duty_type_id"] for row in main_type_row.source_fingerprint["duty_rows"]
    } == {str(scenario["cross_quarter"].duty_type_id)}

    july_first = next(
        row for row in main_type_row.source_fingerprint["duty_rows"] if row["day"] == "2026-07-01"
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

    assert second_type_row.duty_type_id == second_type.id
    assert second_type_row.raw_day_count == 2
    assert second_type_row.effective_weighted_days == Decimal("2.000000")
    assert second_type_row.duty_score == Decimal("4.000000")
    assert second_type_row.adjustment_score == Decimal("0.000000")
    assert second_type_row.source_fingerprint["adjustments"] == []
    assert {
        row["duty_type_id"] for row in second_type_row.source_fingerprint["duty_rows"]
    } == {str(second_type.id)}

    assert aggregate_row.duty_type_id is None
    assert aggregate_row.raw_day_count == 0
    assert aggregate_row.effective_weighted_days == Decimal("0.000000")
    assert aggregate_row.duty_score == Decimal("0.000000")
    assert aggregate_row.adjustment_score == Decimal("5.000000")
    assert aggregate_row.source_fingerprint == {
        "duty_rows": [],
        "overrides": [],
        "dismissals": [],
        "adjustments": [
            {
                "adjustment_id": str(scenario["primary_adjustment"].id),
                "delta": "5.00",
                "created_at": "2026-07-15T12:00:00+00:00",
            }
        ],
    }

    assert persisted_total.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert persisted_total.duty_score == Decimal("6.700000")
    assert persisted_total.adjustment_score == Decimal("5.000000")
    assert persisted_total.cumulative_score == Decimal("11.700000")
    assert persisted_total.shift_count == 3

    assert persisted_quarter_total.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert persisted_quarter_total.raw_day_count == 7
    assert persisted_quarter_total.effective_weighted_days == Decimal("4.700000")
    assert persisted_quarter_total.duty_score == Decimal("6.700000")
    assert persisted_quarter_total.adjustment_score == Decimal("5.000000")
    assert persisted_quarter_total.total_score == Decimal("11.700000")

    assert state.canonical_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert state.backfill_complete is False
    assert state.resume_after_soldier_id is None
    assert state.resume_after_quarter_start is None


def test_rebuild_projection_bucket_replaces_requested_zero_bucket_with_aggregate_row(admin_session):
    soldier = create_soldier(admin_session, personal_number="score-proj-zero")
    target_quarter = date(2026, 10, 1)
    stale_type = _duty_type(admin_session, name="score-projection-stale-duty")
    admin_session.add(
        SoldierQuarterScoreProjection(
            soldier_id=soldier.id,
            quarter_start=target_quarter,
            duty_type_id=stale_type.id,
            projection_version="stale",
            raw_day_count=4,
            effective_weighted_days=Decimal("4.000000"),
            duty_score=Decimal("9.900000"),
            adjustment_score=Decimal("0.000000"),
            source_fingerprint={"legacy": True},
        )
    )
    admin_session.flush()

    rebuild_projection_bucket(admin_session, soldier.id, target_quarter)
    admin_session.flush()

    persisted_rows = _quarter_rows(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    persisted_total = _soldier_total(admin_session, soldier_id=soldier.id)
    persisted_quarter_total = _quarter_total(admin_session, quarter_start_value=target_quarter)

    assert len(persisted_rows) == 1
    aggregate_row = persisted_rows[0]
    assert aggregate_row.duty_type_id is None
    assert aggregate_row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    assert aggregate_row.raw_day_count == 0
    assert aggregate_row.effective_weighted_days == Decimal("0.000000")
    assert aggregate_row.duty_score == Decimal("0.000000")
    assert aggregate_row.adjustment_score == Decimal("0.000000")
    assert aggregate_row.source_fingerprint == {
        "duty_rows": [],
        "overrides": [],
        "dismissals": [],
        "adjustments": [],
    }

    assert persisted_total.cumulative_score == Decimal("0.000000")
    assert persisted_total.shift_count == 0
    assert persisted_quarter_total.total_score == Decimal("0.000000")


def test_backfill_score_projection_is_resumable_by_soldier_and_quarter_and_idempotent(admin_session):
    soldier = create_soldier(admin_session, personal_number="score-proj-history")
    duty_type = _duty_type(admin_session, name="score-projection-history-duty")
    location = _location(admin_session, name="score-projection-history-location")
    for start_date in (
        date(2026, 1, 5),
        date(2026, 4, 5),
        date(2026, 7, 5),
        date(2026, 10, 5),
    ):
        admin_session.add(
            DutyAssignment(
                soldier_id=soldier.id,
                duty_type_id=duty_type.id,
                duty_location_id=location.id,
                start_date=start_date,
                end_date=start_date.replace(day=start_date.day + 1),
                status="published",
            )
        )
    admin_session.flush()

    first_state = backfill_score_projection(admin_session, batch_size=2)
    admin_session.flush()

    first_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).order_by(
            SoldierQuarterScoreProjection.soldier_id,
            SoldierQuarterScoreProjection.quarter_start,
            SoldierQuarterScoreProjection.duty_type_id,
        )
    ).scalars().all()
    assert [(row.soldier_id, row.quarter_start) for row in first_rows] == [
        (soldier.id, date(2026, 1, 1)),
        (soldier.id, date(2026, 4, 1)),
    ]
    assert first_state.backfill_complete is False
    assert first_state.resume_after_soldier_id == soldier.id
    assert first_state.resume_after_quarter_start == date(2026, 4, 1)
    assert _soldier_total(admin_session, soldier_id=soldier.id).cumulative_score == Decimal("2.000000")

    second_state = backfill_score_projection(
        admin_session,
        batch_size=2,
        resume_after=(first_state.resume_after_soldier_id, first_state.resume_after_quarter_start),
    )
    admin_session.flush()

    second_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).order_by(
            SoldierQuarterScoreProjection.soldier_id,
            SoldierQuarterScoreProjection.quarter_start,
            SoldierQuarterScoreProjection.duty_type_id,
        )
    ).scalars().all()
    assert [(row.soldier_id, row.quarter_start) for row in second_rows] == [
        (soldier.id, date(2026, 1, 1)),
        (soldier.id, date(2026, 4, 1)),
        (soldier.id, date(2026, 7, 1)),
        (soldier.id, date(2026, 10, 1)),
    ]
    assert second_state.backfill_complete is True
    assert second_state.resume_after_soldier_id is None
    assert second_state.resume_after_quarter_start is None
    assert _soldier_total(admin_session, soldier_id=soldier.id).cumulative_score == Decimal("4.000000")

    rerun_state = backfill_score_projection(admin_session, batch_size=2)
    admin_session.flush()

    rerun_rows = admin_session.execute(select(SoldierQuarterScoreProjection)).scalars().all()
    assert rerun_state.backfill_complete is False
    assert len(rerun_rows) == 4
    assert len({(row.soldier_id, row.quarter_start, row.duty_type_id) for row in rerun_rows}) == len(
        rerun_rows
    )


def test_projection_tables_enforce_partition_keys_and_foreign_keys(admin_session):
    scenario = _seed_projection_scenario(admin_session)
    rebuild_projection_bucket(admin_session, scenario["primary"].id, scenario["q3"])
    admin_session.flush()

    existing_rows = _quarter_rows(
        admin_session, soldier_id=scenario["primary"].id, quarter_start_value=scenario["q3"]
    )
    duty_row = next(row for row in existing_rows if row.duty_type_id is not None)

    with pytest.raises(IntegrityError):
        with admin_session.begin_nested():
            admin_session.add(
                SoldierQuarterScoreProjection(
                    soldier_id=scenario["primary"].id,
                    quarter_start=scenario["q3"],
                    duty_type_id=duty_row.duty_type_id,
                    projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                    raw_day_count=0,
                    effective_weighted_days=Decimal("0.000000"),
                    duty_score=Decimal("0.000000"),
                    adjustment_score=Decimal("0.000000"),
                    source_fingerprint={},
                )
            )
            admin_session.flush()

    with pytest.raises(IntegrityError):
        with admin_session.begin_nested():
            admin_session.add(
                SoldierQuarterScoreProjection(
                    soldier_id=scenario["primary"].id,
                    quarter_start=scenario["q3"],
                    duty_type_id=None,
                    projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                    raw_day_count=0,
                    effective_weighted_days=Decimal("0.000000"),
                    duty_score=Decimal("0.000000"),
                    adjustment_score=Decimal("0.000000"),
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
                    duty_score=Decimal("0.000000"),
                    adjustment_score=Decimal("0.000000"),
                    cumulative_score=Decimal("0.000000"),
                    shift_count=0,
                )
            )
            admin_session.flush()
