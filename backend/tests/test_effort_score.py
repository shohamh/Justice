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
    compute_burden_share_breakdown,
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
    unit_join_date: date | None = None


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
        soldier_reset_dates={sid: date(2026, 4, 1)},
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
        soldier_reset_dates={sid: date(2025, 1, 1)},
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
        soldier_reset_dates={sid: date(2025, 1, 1)},
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
        soldier_reset_dates={sid: date(2025, 1, 1)},
    )
    data = result[sid]
    expected_offset = int(data.effort_score * EFFORT_SCALE)
    assert data.effort_offset == expected_offset
    assert data.effort_offset >= 0


def test_veteran_gets_full_active_frac_despite_later_shared_quarter_start():
    """Reproduces the bug caught during design review: a soldier already
    active before their OWN branch's reset date must get active_frac=100%
    for the post-reset portion of the quarter, not diluted by an earlier
    date that governs the shared quarter list because some OTHER soldier's
    branch resets earlier."""
    sid = _sid()
    # Active well before any reset date under consideration.
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    # Shared quarter list starts Jul 1 (some other soldier's earlier reset date)
    # but THIS soldier's own resolved reset date is Aug 20, inside the same quarter.
    quarters = [(date(2026, 7, 1), date(2026, 9, 30))]
    unit_scores = {date(2026, 7, 1): Decimal("100")}
    soldier_scores = {date(2026, 7, 1): {sid: Decimal("42")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        soldier_reset_dates={sid: date(2026, 8, 20)},
    )
    # own_floor = Aug 20; q_days = Aug20..Sep30 = 42; soldier already active
    # since before Aug 20 -> active_in_q = 42 -> active_frac = 100%, not 46%.
    assert result[sid].effort_score == Decimal("42") / Decimal("100")


def test_new_arrival_after_own_branch_reset_date_gets_partial_frac():
    """A soldier whose unit_join_date is AFTER their own branch's resolved
    reset date is a genuinely new arrival — active_frac should be below
    100%, computed against their own (already reset-clipped) window."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 9, 1), unit_join_date=date(2026, 9, 1))
    quarters = [(date(2026, 7, 1), date(2026, 9, 30))]
    unit_scores = {date(2026, 7, 1): Decimal("100")}
    soldier_scores = {date(2026, 7, 1): {sid: Decimal("30")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        soldier_reset_dates={sid: date(2026, 8, 20)},
    )
    # own_floor = Aug 20 (branch reset), q_days = 42 (Aug20..Sep30).
    # soldier_start = max(Aug20, Sep1) = Sep1 -> active_in_q = Sep1..Sep30 = 30.
    # active_frac = 30/42 (below 100%, proving the new-arrival dilution applies).
    # With only one quarter contributing, effort_score = A_i/W_i = (s*frac)/(u*frac)
    # = s/u exactly -- active_frac cancels algebraically regardless of its value,
    # so the observable effort_score is s/u; the frac's effect is only visible in
    # W_i / C_over_D, not in this ratio.
    expected_frac = Decimal("30") / Decimal("42")
    assert expected_frac < Decimal("1")  # sanity: genuinely partial activation
    assert abs(result[sid].effort_score - Decimal("30") / Decimal("100")) < Decimal("0.0001")
    # active_frac's real effect shows up in W_i / C_over_D (it cancels out of the
    # effort_score ratio above since there's only one contributing quarter):
    # W_i = unit_score(100) * active_frac(30/42).
    expected_W = Decimal("100") * expected_frac
    expected_C_over_D = Decimal("1") / (expected_W * 1000)
    assert abs(result[sid].C_over_D - expected_C_over_D) < Decimal("0.0000000001")


def test_unit_join_date_used_over_enrolled_at_for_activation():
    """A soldier enrolled_at (roster entry date) later than their real
    unit_join_date must not be penalized for the admin's lag entering them."""
    sid = _sid()
    # Roster entry lagged 2 weeks behind actual unit join.
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 9, 1), unit_join_date=date(2026, 8, 15))
    quarters = [(date(2026, 7, 1), date(2026, 9, 30))]
    unit_scores = {date(2026, 7, 1): Decimal("100")}
    soldier_scores = {date(2026, 7, 1): {sid: Decimal("20")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        soldier_reset_dates={sid: date(2026, 7, 1)},
    )
    # own_floor = Jul 1 (reset date, earlier than unit_join_date), q_days = 92.
    # activation = unit_join_date = Aug 15 (NOT enrolled_at = Sep 1).
    # active_in_q = Aug15..Sep30 = 47.
    # With only one quarter contributing, effort_score = A_i/W_i = (s*frac)/(u*frac)
    # = s/u exactly -- active_frac cancels algebraically; what this test actually
    # proves is that unit_join_date (not the later enrolled_at) is used as the
    # activation date at all (soldier_start check above didn't skip the quarter).
    expected_frac = Decimal(47) / Decimal(92)
    assert expected_frac < Decimal("1")  # sanity: genuinely partial activation
    assert abs(result[sid].effort_score - Decimal("20") / Decimal("100")) < Decimal("0.0001")
    # As above, active_frac's effect is visible in W_i / C_over_D, not effort_score.
    expected_W = Decimal("100") * expected_frac
    expected_C_over_D = Decimal("1") / (expected_W * 1000)
    assert abs(result[sid].C_over_D - expected_C_over_D) < Decimal("0.0000000001")


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


def test_soldier_input_has_unit_join_date_field():
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
    assert s.unit_join_date is None

    s2 = SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=90,
        unit_join_date=date(2025, 6, 1),
    )
    assert s2.unit_join_date == date(2025, 6, 1)


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


def test_transparency_rows_has_burden_share_key():
    """transparency_rows() output dicts must contain a 'burden_share' key."""
    import inspect
    from app.services import scoring as sc
    src = inspect.getsource(sc.transparency_rows)
    assert "burden_share" in src, "transparency_rows must include burden_share in output"


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
    compute_burden_share_breakdown should include future quarters in the returned
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

    breakdown = compute_burden_share_breakdown(
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
    assert breakdown.burden_share > Decimal("0")


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
    test_transparency_rows_has_burden_share_key in this same file."""
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
    from app.services.scoring import _burden_share_reset_date
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


    assert _burden_share_reset_date(admin_session) == date_cls(2021, 4, 1)
    assert admin_session.execute(select(DutyAssignment)).scalars().all()  # sanity: data exists


def test_reset_date_setting_overrides_earliest_duty(admin_session):
    """A configured fairness.reset_date wins over the earliest-duty default —
    quarters before it are excluded from the quarterly-load history."""
    from datetime import date as date_cls

    from app.db.models import SystemSetting
    from app.services.assignments import create_assignment
    from app.services.scoring import _burden_share_reset_date
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

    assert _burden_share_reset_date(admin_session) == date_cls(2026, 4, 1)


def test_default_frame_counts_quarters_before_two_year_window(admin_session):
    """End-to-end: a duty older than the legacy two-year default must land in
    the breakdown when no reset date is configured."""
    from datetime import date as date_cls

    from app.services.assignments import create_assignment
    from app.services.effort_score import compute_burden_share_breakdown
    from app.services.scoring import _burden_share_planning_start, _burden_share_reset_date
    from tests.helpers import create_soldier


    dt, loc = _seed_duty_type(admin_session, "reset-frame")
    s = create_soldier(admin_session, personal_number="9800003")
    s.enrolled_at = date_cls(2021, 1, 1)
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2021, 5, 10), end_date=date_cls(2021, 5, 13), actor_id=None,
    )
    admin_session.flush()

    bd = compute_burden_share_breakdown(
        admin_session,
        soldier=s,
        planning_start=_burden_share_planning_start(admin_session),
        planning_end=_burden_share_planning_start(admin_session),
        reset_date=_burden_share_reset_date(admin_session),
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
    bd = compute_burden_share_breakdown(
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

def test_resolve_reset_dates_uses_nearest_ancestor_override(admin_session):
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.scoring import resolve_reset_dates_for_soldiers
    from tests.helpers import create_soldier

    root = HierarchyNode(level="corps", name="root", path_ids=[])
    admin_session.add(root)
    admin_session.flush()
    root.path_ids = [root.id]

    branch = HierarchyNode(level="division", name="polaris", parent_id=root.id, path_ids=[])
    admin_session.add(branch)
    admin_session.flush()
    branch.path_ids = [root.id, branch.id]

    team = HierarchyNode(level="unit", name="polaris-team", parent_id=branch.id, path_ids=[])
    admin_session.add(team)
    admin_session.flush()
    team.path_ids = [root.id, branch.id, team.id]
    admin_session.flush()

    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides",
        value={str(branch.id): "2026-08-20"},
    ))
    admin_session.flush()

    soldier_on_team = create_soldier(admin_session, personal_number="9900001")
    soldier_on_team.hierarchy_node_id = team.id
    soldier_no_node = create_soldier(admin_session, personal_number="9900002")
    soldier_no_node.hierarchy_node_id = None
    admin_session.flush()

    resolved = resolve_reset_dates_for_soldiers(admin_session, [soldier_on_team, soldier_no_node])

    # soldier_on_team's own node (team) has no override, but its ancestor
    # (branch) does -> nearest-ancestor wins over the global default.
    assert resolved[soldier_on_team.id] == date_cls(2026, 8, 20)
    # No hierarchy node at all -> global default.
    assert resolved[soldier_no_node.id] == date_cls(2026, 7, 1)


def test_resolve_reset_dates_falls_back_to_global_default(admin_session):
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.scoring import resolve_reset_dates_for_soldiers
    from tests.helpers import create_soldier

    node = HierarchyNode(level="division", name="focus", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="9900003")
    s.hierarchy_node_id = node.id
    admin_session.flush()

    resolved = resolve_reset_dates_for_soldiers(admin_session, [s])
    assert resolved[s.id] == date_cls(2026, 7, 1)


def test_compute_effort_data_resolves_reset_date_per_hierarchy(admin_session):
    """Two soldiers in different branches with different reset-date overrides:
    neither's ratio should be computed against the other's window."""
    from datetime import date as date_cls
    from app.db.models import DutyLocation, DutyType, HierarchyNode, SystemSetting
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    focus = HierarchyNode(level="division", name="focus", path_ids=[])
    polaris = HierarchyNode(level="division", name="polaris", path_ids=[])
    admin_session.add_all([focus, polaris])
    admin_session.flush()
    focus.path_ids = [focus.id]
    polaris.path_ids = [polaris.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(polaris.id): "2026-08-20"}
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "cross-branch")

    focus_soldier = create_soldier(admin_session, personal_number="9910001")
    focus_soldier.hierarchy_node_id = focus.id
    focus_soldier.enrolled_at = date_cls(2025, 1, 1)
    polaris_soldier = create_soldier(admin_session, personal_number="9910002")
    polaris_soldier.hierarchy_node_id = polaris.id
    polaris_soldier.enrolled_at = date_cls(2026, 7, 20)
    admin_session.flush()

    # Both soldiers do the same amount of duty in Q3 2026, both fully active
    # since before their OWN branch's reset date.
    create_assignment(
        admin_session, soldier_id=focus_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 7, 5), end_date=date_cls(2026, 7, 15), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=polaris_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 8, 25), end_date=date_cls(2026, 9, 4), actor_id=None,
    )
    admin_session.flush()

    result = compute_effort_data(
        admin_session,
        soldiers=[focus_soldier, polaris_soldier],
        planning_start=date_cls(2026, 10, 1),
        planning_end=date_cls(2026, 10, 1),
    )
    # effort_score alone can't discriminate correct vs. broken resolution here:
    # A_i/W_i cancels active_frac out of the ratio whenever only one quarter
    # contributes (same phenomenon Task 4 hit) — so this asserts C_over_D
    # (proportional to W_i directly) instead, which does NOT cancel it.
    #
    # Focus: own_floor=Jul1 (their own resolved date, = global default),
    # q_days=92 (full Q3), active since 2025 -> active_in_q=92 -> frac=1.0.
    # W_i = unit_score(Q3)=20 (10-day Focus duty + 10-day Polaris duty) * 1.0 = 20.
    # C_over_D = 1/(20*1000) = 0.00005.
    assert abs(result[focus_soldier.id].C_over_D - Decimal("0.00005")) < Decimal("0.0000001")
    # Polaris: own_floor=Aug20 (THEIR OWN branch override, not the global Jul1
    # default). activation=Jul20 < Aug20 -> soldier_start=Aug20 -> q_days=42
    # (Aug20..Sep30), active_in_q=42 -> frac=1.0. W_i=20*1.0=20 -> C_over_D=0.00005
    # -- same as Focus, proving Polaris got a full-active_frac window measured
    # against THEIR OWN reset date, not a truncated one.
    #
    # If resolution had silently forced the global default (Jul1) onto Polaris
    # instead of their branch's Aug20 override, own_floor would be Jul1,
    # q_days=92, soldier_start=max(Jul1,Jul20)=Jul20 -> active_in_q=73 ->
    # frac=73/92 -> W_i=20*73/92=365/23≈15.87 -> C_over_D≈0.000063 -- clearly
    # different from 0.00005, so this assertion WOULD catch that regression.
    assert abs(result[polaris_soldier.id].C_over_D - Decimal("0.00005")) < Decimal("0.0000001")


def test_compute_burden_share_breakdown_agrees_with_compute_effort_data_across_branches(admin_session):
    """Whole-branch-review finding: compute_burden_share_breakdown (single-soldier)
    and compute_effort_data (batch) must produce the SAME effort_score/burden_share
    for the same soldier. Before the fix, compute_burden_share_breakdown used the
    overridden soldier's OWN resolved reset date as the query floor, which narrowed
    the duty-day query and excluded other branches' earlier duty data from the
    unit-total denominator (q_unit_scores) -- silently disagreeing with
    compute_effort_data, which always floors the query at the org-wide minimum
    resolved date. This reuses the exact two-branch/override fixture from
    test_compute_effort_data_resolves_reset_date_per_hierarchy and asserts the two
    entry points now agree for the overridden (Polaris) soldier."""
    from datetime import date as date_cls
    from app.db.models import DutyLocation, DutyType, HierarchyNode, SystemSetting
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    focus = HierarchyNode(level="division", name="focus2", path_ids=[])
    polaris = HierarchyNode(level="division", name="polaris2", path_ids=[])
    admin_session.add_all([focus, polaris])
    admin_session.flush()
    focus.path_ids = [focus.id]
    polaris.path_ids = [polaris.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(polaris.id): "2026-08-20"}
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "cross-branch-agree")

    focus_soldier = create_soldier(admin_session, personal_number="9920001")
    focus_soldier.hierarchy_node_id = focus.id
    focus_soldier.enrolled_at = date_cls(2025, 1, 1)
    polaris_soldier = create_soldier(admin_session, personal_number="9920002")
    polaris_soldier.hierarchy_node_id = polaris.id
    polaris_soldier.enrolled_at = date_cls(2026, 7, 20)
    admin_session.flush()

    create_assignment(
        admin_session, soldier_id=focus_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 7, 5), end_date=date_cls(2026, 7, 15), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=polaris_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 8, 25), end_date=date_cls(2026, 9, 4), actor_id=None,
    )
    admin_session.flush()

    planning_start = date_cls(2026, 10, 1)
    planning_end = date_cls(2026, 10, 1)

    batch_result = compute_effort_data(
        admin_session,
        soldiers=[focus_soldier, polaris_soldier],
        planning_start=planning_start,
        planning_end=planning_end,
    )

    single_result = compute_burden_share_breakdown(
        admin_session,
        soldier=polaris_soldier,
        planning_start=planning_start,
        planning_end=planning_end,
    )

    # The two entry points must agree on the Polaris soldier's burden_share /
    # effort_score, even though compute_burden_share_breakdown only ever sees
    # ONE soldier while compute_effort_data sees both branches at once.
    assert single_result.burden_share == batch_result[polaris_soldier.id].effort_score


def test_compute_effort_data_explicit_reset_date_still_forces_uniform_date(admin_session):
    """Backward compatibility: passing reset_date explicitly still forces
    that single date for every soldier, ignoring any hierarchy overrides.
    The soldier's own node has an override (Aug 20) but the caller forces
    Sep 1 explicitly; activation (Aug 25) sits strictly between the two so
    the test can tell "the forced date actually applied" apart from "the
    override leaked through despite being explicit" -- with activation
    outside both candidate windows, active_frac would come out identical
    either way and the test couldn't tell them apart."""
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    node = HierarchyNode(level="division", name="branch-x", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(node.id): "2026-08-20"}
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "explicit-reset-date")
    s = create_soldier(admin_session, personal_number="9910003")
    s.hierarchy_node_id = node.id
    s.enrolled_at = date_cls(2026, 8, 25)
    admin_session.flush()

    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 9, 5), end_date=date_cls(2026, 9, 15), actor_id=None,
    )
    admin_session.flush()

    # Explicit reset_date (Sep 1) must be what actually governs -- NOT the
    # node's Aug 20 override.
    result = compute_effort_data(
        admin_session,
        soldiers=[s],
        planning_start=date_cls(2026, 10, 1),
        planning_end=date_cls(2026, 10, 1),
        reset_date=date_cls(2026, 9, 1),
    )
    # Correct (forced Sep 1 wins): own_floor=Sep1, q_days=30 (Sep1..Sep30).
    # activation=Aug25 < Sep1 -> soldier_start=Sep1 -> active_in_q=30 -> frac=1.0.
    # W_i = unit_score(Q3, the one 10-day duty) * 1.0 = 10.
    # C_over_D = 1/(10*1000) = 0.0001.
    #
    # If the Aug20 override had wrongly leaked through instead of the explicit
    # Sep1: own_floor=Aug20, q_days=42, soldier_start=max(Aug20,Aug25)=Aug25
    # (activation wins here) -> active_in_q=36 -> frac=36/42 -> W_i=10*36/42≈8.57
    # -> C_over_D≈0.0001167 -- clearly different from 0.0001, so this assertion
    # would catch that regression.
    assert abs(result[s.id].C_over_D - Decimal("0.0001")) < Decimal("0.0000001")


def test_run_algorithm_job_does_not_force_global_reset_date():
    """run_algorithm_job must let compute_effort_data auto-resolve reset date
    per soldier — passing an explicit reset_date= here would silently defeat
    every hierarchy override for the live solve."""
    import inspect
    from app.services import algorithm_bridge as ab

    src = inspect.getsource(ab.run_algorithm_job)
    assert "reset_date=" not in src, (
        "run_algorithm_job must not pass an explicit reset_date to compute_effort_data"
    )


def test_export_solver_inputs_does_not_force_global_reset_date():
    import inspect
    from app.services import algorithm_bridge as ab

    src = inspect.getsource(ab.export_solver_inputs)
    assert "reset_date=" not in src


def test_legacy_transparency_rows_does_not_force_global_reset_date():
    import inspect
    from app.services import scoring as sc

    src = inspect.getsource(sc._legacy_transparency_rows)
    assert "reset_date=" not in src


def test_burden_share_breakdown_route_does_not_force_global_reset_date():
    import inspect
    from app.routes import scoring as scoring_routes

    src = inspect.getsource(scoring_routes.burden_share_breakdown)
    assert "reset_date=" not in src


def test_preview_adjustment_route_does_not_force_global_reset_date():
    import inspect
    from app.routes import score_adjustments

    src = inspect.getsource(score_adjustments.preview_adjustment)
    assert "reset_date=" not in src


# ---------------------------------------------------------------------------
# Generalizing the query-floor fix to 3+ branches with staggered overrides.
#
# The two-branch fix (query_floor = min(global_default, own_reset)) only
# protects against a gap between the global default and THIS soldier's own
# override. A THIRD branch with an override earlier than both -- but still
# inside the same quarter as the two-branch floor -- creates a gap that fix
# doesn't see: duty data in that gap is silently excluded from the query,
# understating the quarter's unit-total (W_i) for every OTHER soldier's
# breakdown, even though a full-org compute_effort_data() batch call would
# have included it (since its own floor is the min over whichever soldiers
# happen to be in that batch, including the third branch).
# ---------------------------------------------------------------------------

def test_burden_share_breakdown_includes_third_branchs_earlier_override_gap(admin_session):
    """Global default (Aug 10, deliberately NOT quarter-aligned) is BETWEEN
    Sparta's earlier override (Jul 15) and Polaris's later one (Aug 20), all
    inside the same quarter (Q3 2026). Sparta has a duty inside that gap
    (Jul 20-30). The two-branch fix's query floor (min(Aug10, Aug20) = Aug10)
    would miss it entirely; the general fix's floor must reach back to the
    earliest override configured ANYWHERE in the system (Jul 15), not just
    the global default and this one soldier's own date."""
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    sparta = HierarchyNode(level="division", name="sparta", path_ids=[])
    polaris = HierarchyNode(level="division", name="polaris-gap", path_ids=[])
    admin_session.add_all([sparta, polaris])
    admin_session.flush()
    sparta.path_ids = [sparta.id]
    polaris.path_ids = [polaris.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-08-10"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides",
        value={str(sparta.id): "2026-07-15", str(polaris.id): "2026-08-20"},
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "third-branch-gap")

    sparta_soldier = create_soldier(admin_session, personal_number="9940001")
    sparta_soldier.hierarchy_node_id = sparta.id
    sparta_soldier.enrolled_at = date_cls(2025, 1, 1)
    polaris_soldier = create_soldier(admin_session, personal_number="9940002")
    polaris_soldier.hierarchy_node_id = polaris.id
    polaris_soldier.enrolled_at = date_cls(2025, 1, 1)
    admin_session.flush()

    # Sparta's duty sits in the gap: after Sparta's own Jul15 override, but
    # before the global default (Aug10) the two-branch fix would floor at.
    create_assignment(
        admin_session, soldier_id=sparta_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 7, 20), end_date=date_cls(2026, 7, 30), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=polaris_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 8, 25), end_date=date_cls(2026, 9, 4), actor_id=None,
    )
    admin_session.flush()

    bd = compute_burden_share_breakdown(
        admin_session,
        soldier=polaris_soldier,
        planning_start=date_cls(2026, 10, 1),
        planning_end=date_cls(2026, 10, 1),
    )
    # Polaris's own quarter clip is unchanged (own_floor=Aug20, q_days=42,
    # active_in_q=42, frac=1.0) -- only the unit-total denominator changes.
    # Two-branch (buggy) floor = Aug10 -> misses Sparta's Jul20-30 duty ->
    # Q3 unit_score = 10 (Polaris only) -> burden_share = 10/10 = 1.0.
    # General fix's floor = Jul15 -> includes Sparta's 10 -> Q3 unit_score =
    # 20 (Sparta + Polaris) -> burden_share = 10/20 = 0.5, matching what a
    # full-org compute_effort_data() batch would produce for this soldier.
    assert bd.burden_share == Decimal("10") / Decimal("20")


def test_compute_effort_data_floor_independent_of_batch_composition(admin_session):
    """The SAME soldier's effort_score must not depend on which OTHER
    soldiers happen to be included in the batch. A narrow batch (just
    Polaris) must reach back to a third branch's (Sparta's) earlier override
    just as a full batch (Sparta + Polaris) would, since Sparta's gap duty
    falls in the same quarter the narrow batch's floor would otherwise stop
    at."""
    from datetime import date as date_cls
    from app.db.models import HierarchyNode, SystemSetting
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    sparta = HierarchyNode(level="division", name="sparta-batch", path_ids=[])
    polaris = HierarchyNode(level="division", name="polaris-batch", path_ids=[])
    admin_session.add_all([sparta, polaris])
    admin_session.flush()
    sparta.path_ids = [sparta.id]
    polaris.path_ids = [polaris.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-08-10"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides",
        value={str(sparta.id): "2026-07-15", str(polaris.id): "2026-08-20"},
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "batch-independence")

    sparta_soldier = create_soldier(admin_session, personal_number="9940003")
    sparta_soldier.hierarchy_node_id = sparta.id
    sparta_soldier.enrolled_at = date_cls(2025, 1, 1)
    polaris_soldier = create_soldier(admin_session, personal_number="9940004")
    polaris_soldier.hierarchy_node_id = polaris.id
    polaris_soldier.enrolled_at = date_cls(2025, 1, 1)
    admin_session.flush()

    create_assignment(
        admin_session, soldier_id=sparta_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 7, 20), end_date=date_cls(2026, 7, 30), actor_id=None,
    )
    create_assignment(
        admin_session, soldier_id=polaris_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_cls(2026, 8, 25), end_date=date_cls(2026, 9, 4), actor_id=None,
    )
    admin_session.flush()

    narrow = compute_effort_data(
        admin_session, soldiers=[polaris_soldier],
        planning_start=date_cls(2026, 10, 1), planning_end=date_cls(2026, 10, 1),
    )
    full = compute_effort_data(
        admin_session, soldiers=[sparta_soldier, polaris_soldier],
        planning_start=date_cls(2026, 10, 1), planning_end=date_cls(2026, 10, 1),
    )
    assert narrow[polaris_soldier.id].effort_score == full[polaris_soldier.id].effort_score
    assert narrow[polaris_soldier.id].effort_score == Decimal("10") / Decimal("20")
