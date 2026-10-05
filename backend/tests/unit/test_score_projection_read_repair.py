from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text

from app.db.models import (
    ScoreProjectionDirtyBucket,
    ScoreProjectionQuarterTotal,
    ScoreProjectionState,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services import score_projection, scoring
from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION
from app.services.scoring import _refresh_required_soldier_totals
from tests.helpers import create_soldier


def test_projection_readiness_omits_exact_keys_covered_by_required_quarter(monkeypatch):
    covered_soldier = uuid4()
    uncovered_soldier = uuid4()
    covered_quarter = date(2026, 1, 1)
    uncovered_quarter = date(2026, 4, 1)
    required_checks = []
    session = object()

    monkeypatch.setattr(scoring, "_projection_state_is_complete", lambda _session: True)
    monkeypatch.setattr(score_projection, "_bucket_health_counts", lambda *_args, **_kwargs: (0, 0))
    monkeypatch.setattr(
        score_projection, "_dirty_or_divergent_projection_keys", lambda *_args, **_kwargs: set()
    )
    monkeypatch.setattr(
        scoring, "_required_quarter_totals_match_projection_rows", lambda *_args, **_kwargs: True
    )

    def record_required(_session, required):
        required_checks.append(required)
        return True

    monkeypatch.setattr(score_projection, "projection_is_current", record_required)

    assert scoring._ensure_projection_ready(
        session,
        keys={(covered_soldier, covered_quarter), (uncovered_soldier, uncovered_quarter)},
        quarter_starts={covered_quarter},
    )
    assert required_checks == [{covered_quarter, (uncovered_soldier, uncovered_quarter)}]


def test_refresh_required_soldier_totals_batches_missing_and_implicated_rows(
    admin_session, monkeypatch
):
    soldiers = [
        create_soldier(admin_session, personal_number=f"88900{index}")
        for index in range(6)
    ]
    quarter_starts = (date(2026, 1, 1), date(2026, 4, 1))
    repeated_assignment_id = uuid4()
    expected_totals = {}

    for index, soldier in enumerate(soldiers):
        duty_score = Decimal(index + 1) + Decimal(index + 10)
        adjustment_score = Decimal(index) / Decimal(20)
        expected_totals[soldier.id] = (duty_score, adjustment_score, index != 0)
        if index == 0:
            assignment_ids = (repeated_assignment_id, repeated_assignment_id)
        else:
            assignment_ids = (uuid4(), uuid4())
        for quarter_start, row_duty, row_adjustment, assignment_id in zip(
            quarter_starts,
            (Decimal(index + 1), Decimal(index + 10)),
            (Decimal(index) / Decimal(10), -Decimal(index) / Decimal(20)),
            assignment_ids,
            strict=True,
        ):
            admin_session.add(
                SoldierQuarterScoreProjection(
                    soldier_id=soldier.id,
                    quarter_start=quarter_start,
                    duty_type_id=None,
                    projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                    effective_weighted_days=Decimal("1"),
                    duty_score=row_duty,
                    adjustment_score=row_adjustment,
                    raw_day_count=1,
                    source_fingerprint={
                        "duty_rows": [{"assignment_id": str(assignment_id)}],
                    },
                )
            )

    # Three totals are missing, one has an old version, and one is implicated
    # by a divergence marker. The sixth row is deliberately unmarked: read-path
    # trust semantics leave an unmarked canonical total alone.
    for index in (3, 4, 5):
        admin_session.add(
            SoldierScoreProjection(
                soldier_id=soldiers[index].id,
                projection_version=(
                    "old" if index == 3 else SCORE_PROJECTION_CANONICAL_VERSION
                ),
                duty_score=Decimal("999"),
                adjustment_score=Decimal("99"),
                cumulative_score=Decimal("1098"),
                shift_count=99,
            )
        )
    admin_session.add(
        ScoreProjectionDirtyBucket(
            soldier_id=soldiers[4].id,
            quarter_start=quarter_starts[0],
            status="clean",
            divergence={"expected": "different"},
        )
    )
    admin_session.flush()

    aggregate_statements = []

    def count_projection_aggregates(_connection, _cursor, statement, _parameters, _context, _many):
        if "from soldier_quarter_score_projection p" in statement.lower():
            aggregate_statements.append(statement)

    engine = admin_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_projection_aggregates)
    monkeypatch.setattr(
        admin_session,
        "commit",
        lambda: pytest.fail("read-side projection repair must not commit"),
    )
    try:
        assert _refresh_required_soldier_totals(
            admin_session, soldier_ids={soldier.id for soldier in soldiers}
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_projection_aggregates)

    assert len(aggregate_statements) <= 1
    assert admin_session.in_transaction()
    for soldier in soldiers[:5]:
        row = admin_session.execute(
            select(SoldierScoreProjection).where(
                SoldierScoreProjection.soldier_id == soldier.id
            )
        ).scalar_one()
        duty_score, adjustment_score, has_two_distinct_shifts = expected_totals[soldier.id]
        assert row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
        assert row.duty_score == duty_score
        assert row.adjustment_score == adjustment_score
        assert row.cumulative_score == duty_score + adjustment_score
        assert row.shift_count == (2 if has_two_distinct_shifts else 1)

    trusted_unmarked = admin_session.execute(
        select(SoldierScoreProjection).where(
            SoldierScoreProjection.soldier_id == soldiers[5].id
        )
    ).scalar_one()
    assert trusted_unmarked.duty_score == Decimal("999")
    assert trusted_unmarked.projection_version == SCORE_PROJECTION_CANONICAL_VERSION


def test_transparency_projection_reuses_its_planning_start(admin_session, monkeypatch):
    soldier = create_soldier(admin_session, personal_number="8890006")
    admin_session.add(
        SoldierScoreProjection(
            soldier_id=soldier.id,
            projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
            duty_score=Decimal("0"),
            adjustment_score=Decimal("0"),
            cumulative_score=Decimal("0"),
            shift_count=0,
        )
    )
    admin_session.flush()

    reset_date = date(2026, 10, 1)
    monkeypatch.setattr(scoring, "_burden_share_reset_date", lambda _session: reset_date)
    monkeypatch.setattr(scoring, "_burden_share_quarter_windows", lambda *args, **kwargs: [])
    monkeypatch.setattr(scoring, "_projection_data_keys_for_soldiers", lambda *_args: set())
    monkeypatch.setattr(scoring, "_ensure_projection_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(scoring, "_bulk_active_days", lambda _session, _soldiers: {soldier.id: 1})
    monkeypatch.setattr(scoring, "globally_exempted_soldier_ids", lambda _session: set())
    monkeypatch.setattr(scoring, "_active_exemptions_by_soldier", lambda _session: {})
    monkeypatch.setattr(
        scoring,
        "resolve_reset_dates_for_soldiers",
        lambda _session, soldiers: {item.id: reset_date for item in soldiers},
    )
    monkeypatch.setattr(
        scoring, "_projection_burden_share_inputs", lambda *args, **kwargs: ([], {}, {})
    )

    planning_start_queries = []

    def count_planning_start_queries(_connection, _cursor, statement, _parameters, _context, _many):
        if "select max(duty_assignments.end_date)" in statement.lower():
            planning_start_queries.append(statement)

    engine = admin_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_planning_start_queries)
    try:
        result = scoring._try_projected_transparency_rows(admin_session)
    finally:
        event.remove(engine, "before_cursor_execute", count_planning_start_queries)

    assert result is not None
    assert len(result["rows"]) == 1
    assert len(planning_start_queries) == 1


def test_transparency_readiness_uses_compact_quarters_for_full_active_population(
    admin_session, monkeypatch
):
    active = [create_soldier(admin_session, personal_number=f"889010{i}") for i in range(2)]
    departed = create_soldier(admin_session, personal_number="8890102")
    departed.left_at = date(2026, 1, 1)
    q1, q2, q3 = date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1)
    partitions = [(soldier, q1) for soldier in active] + [(active[0], q2), (departed, q3)]
    for soldier, quarter in partitions:
        admin_session.add(
            SoldierQuarterScoreProjection(
                soldier_id=soldier.id,
                quarter_start=quarter,
                duty_type_id=None,
                projection_version=(
                    "old" if soldier.id == active[0].id and quarter == q2
                    else SCORE_PROJECTION_CANONICAL_VERSION
                ),
                effective_weighted_days=Decimal("0"),
                duty_score=Decimal("0"),
                adjustment_score=Decimal("0"),
                source_fingerprint={},
            )
        )
    for quarter in (q1, q2):
        admin_session.add(
            ScoreProjectionQuarterTotal(
                quarter_start=quarter,
                projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                effective_weighted_days=Decimal("0"),
                duty_score=Decimal("0"),
                adjustment_score=Decimal("0"),
                total_score=Decimal("0"),
            )
        )
    admin_session.add(
        ScoreProjectionState(
            projection_key="score_projection",
            canonical_version=SCORE_PROJECTION_CANONICAL_VERSION,
            backfill_complete=True,
        )
    )
    admin_session.add(
        ScoreProjectionDirtyBucket(
            soldier_id=active[1].id,
            quarter_start=q1,
            status="dirty",
        )
    )
    for soldier in active:
        admin_session.add(
            SoldierScoreProjection(
                soldier_id=soldier.id,
                projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
                duty_score=Decimal("0"),
                adjustment_score=Decimal("0"),
                cumulative_score=Decimal("0"),
                shift_count=0,
            )
        )
    admin_session.flush()

    monkeypatch.setattr(scoring, "_burden_share_reset_date", lambda _session: q1)
    monkeypatch.setattr(scoring, "_burden_share_planning_start", lambda _session: q2)
    monkeypatch.setattr(
        scoring,
        "_burden_share_quarter_windows",
        lambda *_args, **_kwargs: [(q1, date(2026, 3, 31), q1)],
    )
    monkeypatch.setattr(
        scoring,
        "resolve_reset_dates_for_soldiers",
        lambda _session, soldiers: {soldier.id: q1 for soldier in soldiers},
    )
    monkeypatch.setattr(
        scoring, "_bulk_active_days", lambda _session, soldiers: {s.id: 1 for s in soldiers}
    )
    monkeypatch.setattr(scoring, "globally_exempted_soldier_ids", lambda _session: set())
    monkeypatch.setattr(scoring, "_active_exemptions_by_soldier", lambda _session: {})
    monkeypatch.setattr(
        scoring,
        "_projection_data_keys_for_soldiers",
        lambda *_args: pytest.fail("global transparency must not enumerate soldier-quarter pairs"),
    )
    original_readiness = scoring._ensure_projection_ready
    checks = []

    def record_readiness(session, **kwargs):
        checks.append(kwargs)
        return original_readiness(session, **kwargs)

    original_marker_check = score_projection.projection_has_pending_markers
    marker_checks = []

    def record_pending_marker_check(session, *, soldier_ids):
        marker_checks.append(frozenset(soldier_ids))
        return original_marker_check(session, soldier_ids=soldier_ids)

    monkeypatch.setattr(scoring, "_ensure_projection_ready", record_readiness)
    monkeypatch.setattr(score_projection, "projection_has_pending_markers", record_pending_marker_check)
    projection_select_lists = []
    original_execute = admin_session.execute

    def capture_projection_selects(statement, *args, **kwargs):
        selected_names = [column.name for column in getattr(statement, "selected_columns", ())]
        from_tables = getattr(statement, "get_final_froms", lambda: [])()
        reads_projection_table = any(
            getattr(table, "name", None) == SoldierScoreProjection.__tablename__
            for table in from_tables
        )
        if reads_projection_table and "cumulative_score" in selected_names and "shift_count" in selected_names:
            projection_select_lists.append(selected_names)
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(admin_session, "execute", capture_projection_selects)
    result = scoring._try_projected_transparency_rows(admin_session)

    assert result is not None
    assert projection_select_lists.count(["soldier_id", "cumulative_score", "shift_count"]) == 1
    assert {row["soldier_id"] for row in result["rows"]} == {s.id for s in active}
    active_ids = {soldier.id for soldier in active}
    assert checks == [
        {
            "keys": set(),
            "quarter_starts": {q1, q2},
            "total_soldier_ids": active_ids,
            "bucket_soldier_ids": active_ids,
        }
    ]
    assert marker_checks == [frozenset(active_ids)]
    assert admin_session.execute(
        select(ScoreProjectionDirtyBucket.status).where(
            ScoreProjectionDirtyBucket.soldier_id == active[1].id
        )
    ).scalar_one() == "current"
    assert not admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == active[0].id,
            SoldierQuarterScoreProjection.quarter_start == q2,
            SoldierQuarterScoreProjection.projection_version == "old",
        )
    ).scalars().all()
    assert result == scoring._legacy_transparency_rows(admin_session)


def test_aggregate_error_rolls_back_repair_savepoint_and_allows_legacy_fallback(
    admin_session, monkeypatch
):
    soldier = create_soldier(admin_session, personal_number="8890007")
    admin_session.flush()

    def fail_aggregate(session, _soldier_ids):
        session.execute(text("SELECT 1 / 0")).all()

    def projected_read(session, *, viewer=None):
        assert not _refresh_required_soldier_totals(session, soldier_ids={soldier.id})
        assert session.execute(select(1)).scalar_one() == 1
        return None

    monkeypatch.setattr(score_projection, "_expected_soldier_totals_by_id", fail_aggregate)
    monkeypatch.setattr(scoring, "_try_projected_transparency_rows", projected_read)

    result = scoring.transparency_rows(admin_session)

    assert [row["soldier_id"] for row in result["rows"]] == [soldier.id]
