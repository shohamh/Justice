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

    New formula: A_i = 0 (no personal score), W_i = U_q × active_frac = 100 × 1.0 = 100.
    C_over_D = 1 / (W_i × 1000) = 1/100000 = 1e-5.
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
    # W_i = 100 × 1.0 = 100  (unit_score × active_frac)
    # C_over_D = 1 / (100 × 1000) = 1e-5
    assert abs(data.C_over_D - Decimal("0.00001")) < Decimal("0.000001")


def test_veteran_perfect_average():
    """Veteran with exactly 1/N share each quarter → effort_score = 1/N."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    # 2 full quarters, each with unit_score=100, soldier got 10 (1/10 = 1/N for N=10)
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
    # A_i = 10×1.0 + 10×1.0 = 20, W_i = 100×1.0 + 100×1.0 = 200
    # effort_score = 20/200 = 0.1
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
    # Q1: soldier not enrolled → skip. Q2: active_frac=1.0, s=10, U=100
    # A_i = 10×1.0 = 10, W_i = 100×1.0 = 100
    # effort_score = 10/100 = 0.1, C_over_D = 1/(100×1000) = 1e-5
    assert abs(data.effort_score - Decimal("0.1")) < Decimal("0.0001")
    assert abs(data.C_over_D - Decimal("0.00001")) < Decimal("0.000001")


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
    """After injection, effort_per_milli = int(C_over_D × EFFORT_SCALE) when unit_score > 0."""
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
    # C_over_D = 1/(W_global × 1000). The bridge multiplies it by EFFORT_SCALE directly.
    effort_map = {
        sid: EffortData(
            effort_score=Decimal("0.1"), C_over_D=Decimal("0.5"),
            effort_offset=int(Decimal("0.1") * EFFORT_SCALE),
        )
    }
    inject_effort_scores([s], [block], effort_map)
    assert s.effort_offset == int(Decimal("0.1") * EFFORT_SCALE)
    # effort_per_milli = int(C_over_D × EFFORT_SCALE) — no unit_score_milli division
    expected = int(Decimal("0.5") * EFFORT_SCALE)
    assert s.effort_per_milli == expected


def test_inject_effort_scores_zero_when_no_duties():
    """effort_per_milli stays 0 when the planning window has no duties."""
    sid = uuid.uuid4()
    s = SoldierInput(
        id=sid, enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"), active_days=90,
    )
    effort_map = {
        sid: EffortData(
            effort_score=Decimal("0.1"), C_over_D=Decimal("0.5"),
            effort_offset=int(Decimal("0.1") * EFFORT_SCALE),
        )
    }
    inject_effort_scores([s], [], effort_map)  # empty duty_blocks
    assert s.effort_per_milli == 0


def test_transparency_rows_has_effort_score_key():
    """transparency_rows() output dicts must contain an 'effort_score' key."""
    import inspect
    from app.services import scoring as sc
    src = inspect.getsource(sc.transparency_rows)
    assert "effort_score" in src, "transparency_rows must include effort_score in output"


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


def test_pending_quarter_scores_apportions_by_day():
    """_pending_quarter_scores splits a duty's total score across the calendar
    quarter(s) it touches, keyed by quarter_start."""
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
    pending_duties, that duty looks like 100% of the quarter. With pending_duties
    representing 93 more duty-equivalents about to be planned into the same quarter,
    her share correctly drops to 7%.
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

    planning_start = date(2026, 10, 1)
    planning_end = date(2026, 10, 1)
    reset_date = date(2026, 7, 1)

    without = compute_effort_data(
        admin_session, soldiers=[victim, control],
        planning_start=planning_start, planning_end=planning_end, reset_date=reset_date,
    )
    assert without[victim.id].effort_score == Decimal("1")  # 7/7 -- the bug
    assert without[control.id].effort_score == Decimal("0")

    # 93 more single-day duty-equivalents about to be planned into the same quarter.
    pending = [
        DutyBlock(
            id=uuid.uuid4(), duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 8, 1) + timedelta(days=i),
            end_date=date(2026, 8, 2) + timedelta(days=i),
            score_per_day=Decimal("1.00"),
        )
        for i in range(93)
    ]

    withp = compute_effort_data(
        admin_session, soldiers=[victim, control],
        planning_start=planning_start, planning_end=planning_end, reset_date=reset_date,
        pending_duties=pending,
    )
    # 61 of the 93 pending duties fall in Q3 (Aug 1..Sep 30), 32 spill into Q4.
    # Q3: 7 published + 61 pending = 68; Q4: 32 pending.
    # New formula: A_i = 7×1.0 = 7, W_i = 68×1.0 + 32×1.0 = 100
    # effort_score = 7/100 = 0.07 — a fraction of the bugged 7/7.
    assert Decimal("0.069") < withp[victim.id].effort_score < Decimal("0.071")
    assert withp[control.id].effort_score == Decimal("0")


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
# Frame of reference: default history window starts at the earliest published
# duty of ANY soldier; fairness.reset_date overrides it.
# ---------------------------------------------------------------------------

def _seed_duty_type(session, name: str):
    from decimal import Decimal

    from app.db.models import DutyLocation, DutyType


    dt = DutyType(name=name, score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc-{name}")
    session.add_all([dt, loc])
    session.flush()
    return dt, loc


def test_reset_date_defaults_to_earliest_published_duty(admin_session):
    """Without fairness.reset_date, the frame of reference is the calendar
    quarter containing the earliest duty assigned to any soldier — however old."""
    from datetime import date as date_cls

    from sqlalchemy import select

    from app.db.models import DutyAssignment
    from app.services.assignments import create_assignment
    from app.services.scoring import _effort_reset_date
    from tests.helpers import create_soldier

    dt, loc = _seed_duty_type(admin_session, "reset-earliest")
    s = create_soldier(admin_session, personal_number="9800001")
    admin_session.flush()
    # An old duty (well beyond the legacy two-year look-back) and a recent one.
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2021, 5, 10), end_date=date_cls(2021, 5, 12), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 7, 1), end_date=date_cls(2026, 7, 2), actor_id=None,
    )
    admin_session.flush()


    assert _effort_reset_date(admin_session) == date_cls(2021, 4, 1)
    assert admin_session.execute(select(DutyAssignment)).scalars().all()  # sanity: data exists


def test_reset_date_setting_overrides_earliest_duty(admin_session):
    """A configured fairness.reset_date wins over the earliest-duty default —
    quarters before it are excluded from the quarterly-load history."""
    from datetime import date as date_cls

    from app.db.models import SystemSetting
    from app.services.assignments import create_assignment
    from app.services.scoring import _effort_reset_date
    from tests.helpers import create_soldier

    dt, loc = _seed_duty_type(admin_session, "reset-setting")
    s = create_soldier(admin_session, personal_number="9800002")
    admin_session.flush()
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2021, 5, 10), end_date=date_cls(2021, 5, 12), actor_id=None,
    )
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-04-01"))
    admin_session.flush()

    assert _effort_reset_date(admin_session) == date_cls(2026, 4, 1)


def test_default_frame_counts_quarters_before_two_year_window(admin_session):
    """End-to-end: a duty older than the legacy two-year default must land in
    the breakdown when no reset date is configured."""
    from datetime import date as date_cls

    from app.services.assignments import create_assignment
    from app.services.effort_score import compute_effort_breakdown
    from app.services.scoring import _effort_planning_start, _effort_reset_date
    from tests.helpers import create_soldier


    dt, loc = _seed_duty_type(admin_session, "reset-frame")
    s = create_soldier(admin_session, personal_number="9800003")
    s.enrolled_at = date_cls(2021, 1, 1)
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2021, 5, 10), end_date=date_cls(2021, 5, 13), actor_id=None,
    )
    admin_session.flush()

    bd = compute_effort_breakdown(
        admin_session,
        soldier=s,
        planning_start=_effort_planning_start(admin_session),
        planning_end=_effort_planning_start(admin_session),
        reset_date=_effort_reset_date(admin_session),
    )
    labels = [q.quarter_label for q in bd.quarters]
    assert "Q2 2021" in labels
    q2 = next(q for q in bd.quarters if q.quarter_label == "Q2 2021")
    assert q2.soldier_score == Decimal("3")  # 3 days × score_per_day 1.0
    assert bd.A_i > 0


# ---------------------------------------------------------------------------
# Traceability: per-quarter contributions behind the effort breakdown
# ---------------------------------------------------------------------------

def test_breakdown_contributions_reconstruct_scores(admin_session):
    """Each quarter's contributions (duty spans + manual adjustments) must sum
    to that quarter's soldier_score, carry the duty type name, day counts and
    multiplier provenance."""
    from datetime import date as date_cls

    from app.db.models import ScoreAdjustment
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    dt_a, loc = _seed_duty_type(admin_session, "trace-a")
    dt_b, _ = _seed_duty_type(admin_session, "trace-b")
    s = create_soldier(admin_session, personal_number="9800004")
    s.enrolled_at = date_cls(2026, 1, 1)
    admin_session.flush()
    # Q2 2026: 3 days of trace-a; Q3 2026: 2 days of trace-b
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt_a.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 5, 1), end_date=date_cls(2026, 5, 4), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt_b.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 8, 1), end_date=date_cls(2026, 8, 3), actor_id=None,
    )
    adj = ScoreAdjustment(soldier_id=s.id, delta=Decimal("2.50"), reason="מבחן התאמה")
    admin_session.add(adj)
    admin_session.flush()

    planning_start = max(date_cls.today(), date_cls(2026, 9, 30))
    bd = compute_effort_breakdown(
        admin_session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=date_cls(2026, 1, 1),
    )

    by_label = {q.quarter_label: q for q in bd.quarters}
    q2 = by_label["Q2 2026"]
    duties_q2 = [c for c in q2.contributions if c.kind == "duty"]
    assert len(duties_q2) == 1
    assert duties_q2[0].label == "trace-a"
    assert duties_q2[0].days == 3
    assert duties_q2[0].score == Decimal("3")
    assert sum(c.score for c in q2.contributions) == q2.soldier_score

    q3 = by_label["Q3 2026"]
    kinds = {c.kind for c in q3.contributions}
    assert kinds == {"duty", "adjustment"}
    adjustment = next(c for c in q3.contributions if c.kind == "adjustment")
    assert adjustment.score == Decimal("2.50")
    assert adjustment.label == "מבחן התאמה"
    assert sum(c.score for c in q3.contributions) == q3.soldier_score
    assert q3.adjustment_delta == Decimal("2.50")


def test_contribution_multiplier_reflects_dismissal(admin_session):
    """Dismissed days keep their reduced multiplier inside the contribution's
    average multiplier instead of silently inflating the score."""
    from datetime import date as date_cls

    from app.db.models import DutyDismissal
    from app.services.assignments import create_assignment
    from app.services.effort_score import compute_quarter_contributions
    from tests.helpers import create_soldier
    dt, loc = _seed_duty_type(admin_session, "trace-dismissal")
    s = create_soldier(admin_session, personal_number="9800005")
    s.enrolled_at = date_cls(2026, 1, 1)
    admin_session.flush()
    assignment = create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 5, 1), end_date=date_cls(2026, 5, 5), actor_id=None,
    )
    admin_session.add(DutyDismissal(
        duty_assignment_id=assignment.id,
        dismissed_from=date_cls(2026, 5, 3),
        dismissed_to=date_cls(2026, 5, 4),
        reason="שחרור",
    ))
    admin_session.flush()

    contribs = compute_quarter_contributions(
        admin_session, soldier_id=s.id, quarters={date_cls(2026, 4, 1)}
    )[date_cls(2026, 4, 1)]
    # Default multipliers: dismissed_mult=0.0 → May 1–2 paid, May 3–4 zero-weight.
    paid = [c for c in contribs if c.multiplier > 0]
    zeroed = [c for c in contribs if c.multiplier == 0]
    assert len(paid) == 1 and paid[0].days == 2 and paid[0].score == Decimal("2")
    assert len(zeroed) == 1 and zeroed[0].days == 2 and zeroed[0].score == Decimal("0")
    assert "שחרור" in (zeroed[0].detail or "")