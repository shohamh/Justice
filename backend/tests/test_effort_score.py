# backend/tests/test_effort_score.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.algorithm.types import DutyBlock, SoldierInput
from app.services.algorithm_bridge import inject_effort_scores
from app.services.effort_score import (
    EFFORT_SCALE,
    EffortData,
    quarter_end,
    quarter_start,
    _compute_effort_data,
    compute_effort_data,
    compute_effort_breakdown,
)


def test_quarter_start_q1():
    assert quarter_start(date(2026, 2, 15)) == date(2026, 1, 1)


def test_quarter_start_q2():
    assert quarter_start(date(2026, 5, 1)) == date(2026, 4, 1)


def test_quarter_start_q3():
    assert quarter_start(date(2026, 8, 31)) == date(2026, 7, 1)


def test_quarter_start_q4():
    assert quarter_start(date(2026, 11, 1)) == date(2026, 10, 1)


def test_quarter_end_q1():
    assert quarter_end(date(2026, 1, 1)) == date(2026, 3, 31)


def test_quarter_end_q4():
    assert quarter_end(date(2026, 10, 1)) == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# _compute_effort_data unit tests (pure logic, no DB)
# ---------------------------------------------------------------------------

@dataclass
class _MockSoldier:
    id: uuid.UUID
    enrolled_at: date


def _sid():
    return uuid.uuid4()


def test_new_soldier_no_history():
    """Soldier present but with no scored duties → effort_score=0.

    effort_score = A_i / W_i = 0 / 1 = 0. C_over_D = 1/max(W_i,1) = 1.0.
    """
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 4, 1))
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=[(date(2026, 4, 1), date(2026, 6, 30))],
        quarter_unit_scores={date(2026, 4, 1): Decimal("100")},
        quarter_soldier_scores={date(2026, 4, 1): {}},
    )
    data = result[sid]
    assert data.effort_score == Decimal("0")
    # W_i = 1.0 (enrolled on quarter start → active_frac=1.0 for Q2 2026)
    # C_over_D = 1 / max(W_i, 1) = 1.0
    assert abs(data.C_over_D - Decimal("1.0")) < Decimal("0.001")


def test_veteran_perfect_average():
    """Veteran with exactly 1/N share each quarter → effort_score = A/D."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    # 2 full quarters, each with unit_score=100, soldier got 10 (1/10)
    quarters = [
        (date(2025, 1, 1), date(2025, 3, 31)),
        (date(2025, 4, 1), date(2025, 6, 30)),
    ]
    unit_scores = {
        date(2025, 1, 1): Decimal("100"),
        date(2025, 4, 1): Decimal("100"),
    }
    soldier_scores = {
        date(2025, 1, 1): {sid: Decimal("10")},
        date(2025, 4, 1): {sid: Decimal("10")},
    }
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
    )
    data = result[sid]
    # share_q1 = share_q2 = 0.1, active_frac = 1.0 both quarters
    # A_i = 0.1 + 0.1 = 0.2, W_i = 2.0
    # effort_score = A_i / W_i = 0.2 / 2 = 0.1
    assert abs(data.effort_score - Decimal("0.1")) < Decimal("0.0001")


def test_soldier_not_yet_enrolled():
    """Quarter before soldier enrolled → not counted in W_i."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 4, 1))
    quarters = [
        (date(2025, 1, 1), date(2025, 3, 31)),  # soldier not here yet
        (date(2025, 4, 1), date(2025, 6, 30)),  # soldier here
    ]
    unit_scores = {
        date(2025, 1, 1): Decimal("100"),
        date(2025, 4, 1): Decimal("100"),
    }
    soldier_scores = {
        date(2025, 1, 1): {},
        date(2025, 4, 1): {sid: Decimal("10")},
    }
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
    )
    data = result[sid]
    # Q1: soldier not enrolled → skip. Q2: active_frac=1.0, share=0.1
    # A_i=0.1, W_i=1.0
    # effort_score = A_i / W_i = 0.1 / 1 = 0.1
    assert abs(data.effort_score - Decimal("0.1")) < Decimal("0.0001")
    assert abs(data.C_over_D - Decimal("1.0")) < Decimal("0.0001")


def test_effort_offset_integer():
    """effort_offset = int(effort_score × EFFORT_SCALE) and ≥ 0."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    quarters = [(date(2025, 1, 1), date(2025, 3, 31))]
    unit_scores = {date(2025, 1, 1): Decimal("100")}
    soldier_scores = {date(2025, 1, 1): {sid: Decimal("20")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
    )
    data = result[sid]
    expected_offset = int(data.effort_score * EFFORT_SCALE)
    assert data.effort_offset == expected_offset
    assert data.effort_offset >= 0


def test_soldier_input_has_effort_fields():
    """SoldierInput must have effort_offset and effort_per_milli fields."""
    from app.algorithm.types import SoldierInput
    import uuid
    from datetime import date
    from decimal import Decimal

    s = SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=90,
    )
    assert hasattr(s, "effort_offset")
    assert hasattr(s, "effort_per_milli")
    assert s.effort_offset == 0
    assert s.effort_per_milli == 0


def test_inject_effort_scores():
    """After injection, SoldierInput has nonzero effort_per_milli when unit_score > 0."""
    sid = uuid.uuid4()
    s = SoldierInput(
        id=sid, enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"), active_days=90,
    )
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
        score_per_day=Decimal("0.5"),
    )
    # end_date is exclusive, so duration = 6 days: unit_score_milli = int(0.5 * 6 * 1000) = 3000
    # effort data: effort_score=0.1, C_over_D=0.5
    effort_map = {
        sid: EffortData(
            effort_score=Decimal("0.1"), C_over_D=Decimal("0.5"),
            effort_offset=int(Decimal("0.1") * EFFORT_SCALE),
        )
    }
    inject_effort_scores([s], [block], effort_map)
    assert s.effort_offset == int(Decimal("0.1") * EFFORT_SCALE)
    # effort_per_milli = int(0.5 / 3000 × EFFORT_SCALE) = int(166666) = 166666
    expected = int(Decimal("0.5") / 3000 * EFFORT_SCALE)
    assert s.effort_per_milli == expected


def test_inject_effort_scores_uses_score_days_not_calendar_days_touched():
    """A block touching 8 calendar days but spanning exactly 7*24h should contribute
    unit_score_milli as if it were 7 days, not 8."""
    sid = uuid.uuid4()
    s = SoldierInput(
        id=sid, enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"), active_days=90,
    )
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 9),  # 8 calendar days touched
        score_per_day=Decimal("0.5"), start_time="14:00", end_time="14:00",  # exactly 7*24h
    )
    effort_map = {
        sid: EffortData(
            effort_score=Decimal("0.1"), C_over_D=Decimal("0.5"),
            effort_offset=int(Decimal("0.1") * EFFORT_SCALE),
        )
    }
    inject_effort_scores([s], [block], effort_map)
    # unit_score_milli = int(0.5 * 7 * 1000) = 3500 (score_days=7), not int(0.5*8*1000)=4000
    expected = int(Decimal("0.5") / 3500 * EFFORT_SCALE)
    assert s.effort_per_milli == expected


def test_transparency_rows_has_effort_score_key():
    """transparency_rows() output dicts must contain an 'effort_score' key."""
    import inspect
    from app.services import scoring as sc
    src = inspect.getsource(sc.transparency_rows)
    assert "effort_score" in src, "transparency_rows must include effort_score in output"


def test_run_algorithm_job_passes_pending_duties_to_compute_effort_data():
    """run_algorithm_job must pass its own `duties` list as `pending_duties` to
    compute_effort_data, so the algorithm's fairness input accounts for the
    workload it is about to assign (see test_pending_duties_dilute_thin_quarter_share
    for why this matters). Source-inspection style matches
    test_transparency_rows_has_effort_score_key in this same file."""
    import inspect
    from app.services import algorithm_bridge as ab

    src = inspect.getsource(ab.run_algorithm_job)
    assert "pending_duties=duties" in src, (
        "run_algorithm_job's compute_effort_data(...) call must pass pending_duties=duties"
    )


# ---------------------------------------------------------------------------
# Integration tests: future published duties beyond planning_end
# ---------------------------------------------------------------------------

def test_future_duties_increase_effort_offset(admin_session):
    """
    Soldier with heavy future published duties (after planning_end) should have
    a higher effort_offset than a soldier with light future published duties.
    Soldiers with no future duties should be unaffected (offset = 0 when no history).
    """
    from decimal import Decimal
    from app.db.models import DutyLocation, DutyType
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    # Create duty type with score = 1.0 per day
    dt = DutyType(name="שמירה-future", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name="מוצב-future")
    admin_session.add(loc)
    admin_session.flush()

    # Three soldiers enrolled long before the planning window
    enrolled = date(2025, 1, 1)
    s_heavy = create_soldier(admin_session, personal_number="9700001")
    s_heavy.enrolled_at = enrolled
    s_light = create_soldier(admin_session, personal_number="9700002")
    s_light.enrolled_at = enrolled
    s_none = create_soldier(admin_session, personal_number="9700003")
    s_none.enrolled_at = enrolled
    admin_session.flush()

    # Planning window: 2026-Q3 (Jul–Sep)
    planning_start = date(2026, 7, 1)
    planning_end = date(2026, 9, 30)
    reset_date = date(2025, 1, 1)

    # Future duties in Q4 2026 (after planning_end)
    # s_heavy gets 30 days, s_light gets 3 days, s_none gets nothing
    create_assignment(
        admin_session,
        soldier_id=s_heavy.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 30),
        actor_id=None,
    )
    create_assignment(
        admin_session,
        soldier_id=s_light.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 3),
        actor_id=None,
    )
    admin_session.flush()

    soldiers = [s_heavy, s_light, s_none]
    result = compute_effort_data(
        admin_session,
        soldiers=soldiers,
        planning_start=planning_start,
        planning_end=planning_end,
        reset_date=reset_date,
    )

    heavy_data = result[s_heavy.id]
    light_data = result[s_light.id]
    none_data = result[s_none.id]

    # s_heavy has more future duties → higher effort_offset
    assert heavy_data.effort_offset > light_data.effort_offset, (
        f"heavy ({heavy_data.effort_offset}) should exceed light ({light_data.effort_offset})"
    )
    # s_light has more than none
    assert light_data.effort_offset > none_data.effort_offset, (
        f"light ({light_data.effort_offset}) should exceed none ({none_data.effort_offset})"
    )
    # s_none has no duties anywhere → effort_score = 0, offset = 0
    assert none_data.effort_score == Decimal("0")
    assert none_data.effort_offset == 0


def test_planning_window_duties_excluded_from_offset(admin_session):
    """
    Published assignments inside the planning window must NOT affect effort_offset.
    Only past and future (beyond planning_end) duties count.
    """
    from decimal import Decimal
    from app.db.models import DutyLocation, DutyType
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    dt = DutyType(name="שמירה-excl", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name="מוצב-excl")
    admin_session.add(loc)
    admin_session.flush()

    enrolled = date(2025, 1, 1)
    s_window = create_soldier(admin_session, personal_number="9700004")
    s_window.enrolled_at = enrolled
    s_clean = create_soldier(admin_session, personal_number="9700005")
    s_clean.enrolled_at = enrolled
    admin_session.flush()

    planning_start = date(2026, 7, 1)
    planning_end = date(2026, 9, 30)
    reset_date = date(2025, 1, 1)

    # s_window gets a duty INSIDE the planning window (should be excluded)
    create_assignment(
        admin_session,
        soldier_id=s_window.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 5),
        end_date=date(2026, 7, 10),
        actor_id=None,
    )
    admin_session.flush()

    result = compute_effort_data(
        admin_session,
        soldiers=[s_window, s_clean],
        planning_start=planning_start,
        planning_end=planning_end,
        reset_date=reset_date,
    )

    # Planning window is controlled by solver; neither soldier should have offset from it
    assert result[s_window.id].effort_offset == result[s_clean.id].effort_offset == 0


def test_future_quarters_appear_in_breakdown(admin_session):
    """
    compute_effort_breakdown should include future quarters in the returned
    quarter_details list when there are published assignments after planning_end.
    """
    from decimal import Decimal
    from app.db.models import DutyLocation, DutyType
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    dt = DutyType(name="שמירה-bd2", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name="מוצב-bd2")
    admin_session.add(loc)
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="9700006")
    s.enrolled_at = date(2025, 1, 1)
    admin_session.flush()

    planning_start = date(2026, 7, 1)
    planning_end = date(2026, 9, 30)
    reset_date = date(2025, 1, 1)

    # Assign a future duty in Q4 2026
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        actor_id=None,
    )
    admin_session.flush()

    breakdown = compute_effort_breakdown(
        admin_session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_end,
        reset_date=reset_date,
    )

    # At least one quarter detail should cover Q4 2026 (after planning_end)
    future_quarters = [
        q for q in breakdown.quarters
        if q.quarter_start > planning_end
    ]
    assert future_quarters, "Expected at least one future quarter in breakdown"
    # The future quarter should have a non-zero soldier score
    assert any(q.soldier_score > 0 for q in future_quarters)
    # effort_score should be nonzero since the soldier has future duties
    assert breakdown.effort_score > Decimal("0")


# ---------------------------------------------------------------------------
# pending_duties: dilute thin-quarter denominators with about-to-be-planned work
# ---------------------------------------------------------------------------

def test_pending_quarter_scores_apportions_by_day():
    """_pending_quarter_scores splits a duty's total score across the calendar
    quarter(s) it touches, using score_per_day x score_days (same convention as
    effective_duty_days), keyed by the duty's quarter_start."""
    from app.services.effort_score import _pending_quarter_scores

    @dataclass
    class _Block:
        start_date: date
        end_date: date
        start_time: str
        end_time: str
        score_per_day: Decimal

    # One 7-day duty fully inside Q3 2026 (Jul 1 - Sep 30), score_per_day=1.00
    # -> total score 7, all attributed to quarter_start=2026-07-01.
    block = _Block(
        start_date=date(2026, 7, 13), end_date=date(2026, 7, 20),
        start_time="00:00", end_time="23:59", score_per_day=Decimal("1.00"),
    )
    buckets = _pending_quarter_scores([block])
    assert buckets == {date(2026, 7, 1): Decimal("7")}


def test_pending_duties_dilute_thin_quarter_share(admin_session):
    """
    Reproduces the production bug: a soldier ('victim') has ONE pre-existing
    7-day duty in a quarter that otherwise has zero published activity. Without
    pending_duties, that duty looks like 100% of the quarter (the only data
    point). With pending_duties representing the other 93 duty-equivalents the
    algorithm is about to plan into the SAME quarter, her share correctly drops
    to 7% -- reflecting what the quarter will actually look like once this run
    publishes, not the artificially thin snapshot from before it ran.
    """
    from app.db.models import DutyLocation, DutyType
    from app.algorithm.types import DutyBlock
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    dt = DutyType(name="שמירה-pending", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name="מוצב-pending")
    admin_session.add(loc)
    admin_session.flush()

    enrolled = date(2025, 1, 1)
    victim = create_soldier(admin_session, personal_number="9700010")
    victim.enrolled_at = enrolled
    control = create_soldier(admin_session, personal_number="9700011")
    control.enrolled_at = enrolled
    admin_session.flush()

    # victim's one pre-existing published duty: 7 days @ score 1.00 = 7 total.
    create_assignment(
        admin_session,
        soldier_id=victim.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 13),
        end_date=date(2026, 7, 20),
        actor_id=None,
    )
    admin_session.flush()

    # planning_start chosen so the ENTIRE Q3 2026 quarter is one clipped past
    # quarter (history_end = Sep 30) -> W_i = 1 quarter exactly, so
    # effort_score == that single quarter's share (clean assertion numbers).
    planning_start = date(2026, 10, 1)
    planning_end = date(2026, 10, 1)
    reset_date = date(2026, 7, 1)

    without = compute_effort_data(
        admin_session, soldiers=[victim, control],
        planning_start=planning_start, planning_end=planning_end, reset_date=reset_date,
    )
    assert without[victim.id].effort_score == Decimal("1")  # 7/7 -- the bug
    assert without[control.id].effort_score == Decimal("0")

    # 93 more single-day duty-equivalents about to be planned into the same
    # quarter (Q3 2026), assuming full coverage once the run publishes. Q3 2026
    # only has 92 calendar days, so dates wrap (mod 60, well inside Aug 1-Sep
    # 29) rather than running consecutively -- these are hypothetical
    # duty-equivalents for scoring purposes, not real non-overlapping
    # assignments, so overlapping dates is fine.
    pending = [
        DutyBlock(
            id=uuid.uuid4(), duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 8, 1) + timedelta(days=i % 60),
            end_date=date(2026, 8, 2) + timedelta(days=i % 60),
            score_per_day=Decimal("1.00"),
        )
        for i in range(93)
    ]

    withp = compute_effort_data(
        admin_session, soldiers=[victim, control],
        planning_start=planning_start, planning_end=planning_end, reset_date=reset_date,
        pending_duties=pending,
    )
    assert withp[victim.id].effort_score == Decimal("7") / Decimal("100")  # 7/100, not 7/7
    assert withp[control.id].effort_score == Decimal("0")  # unaffected -- she had nothing before either
