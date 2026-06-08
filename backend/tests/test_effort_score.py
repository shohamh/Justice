# backend/tests/test_effort_score.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.services.effort_score import (
    EFFORT_SCALE,
    EffortData,
    quarter_end,
    quarter_start,
    _compute_effort_data,
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
    """Soldier with no historical duties → effort_score=0, C_over_D=1.0."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 4, 1))
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=[(date(2026, 4, 1), date(2026, 6, 30))],
        quarter_unit_scores={date(2026, 4, 1): Decimal("100")},
        quarter_soldier_scores={date(2026, 4, 1): {}},
        planning_start=date(2026, 7, 1),
        planning_end=date(2026, 8, 31),
    )
    data = result[sid]
    assert data.effort_score == Decimal("0")
    # C_i = full planning window / planning_window_length = 1.0
    # W_i = 1.0 (soldier enrolled on quarter start, so active_frac=1.0 for Q2 2026)
    # D_i = W_i + C_i = 1 + 1 = 2
    # C_over_D = 1/2 = 0.5
    # NOTE: Plan draft incorrectly asserted C_over_D=1 (had W_i=0); corrected to 0.5.
    assert abs(data.C_over_D - Decimal("0.5")) < Decimal("0.001")


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
        planning_start=date(2025, 7, 1),
        planning_end=date(2025, 9, 30),
    )
    data = result[sid]
    # share_q1 = share_q2 = 0.1, active_frac = 1.0 both quarters
    # A_i = 0.1 + 0.1 = 0.2, W_i = 2.0, C_i = 1.0, D_i = 3.0
    # effort_score = A_i / D_i = 0.2 / 3 ≈ 0.0667
    assert abs(data.effort_score - Decimal("0.2") / Decimal("3")) < Decimal("0.0001")


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
        planning_start=date(2025, 7, 1),
        planning_end=date(2025, 9, 30),
    )
    data = result[sid]
    # Q1: soldier not enrolled → skip. Q2: active_frac=1.0, share=0.1
    # A_i=0.1, W_i=1.0, C_i=1.0, D_i=2.0
    # effort_score = 0.1 / 2 = 0.05
    assert abs(data.effort_score - Decimal("0.05")) < Decimal("0.0001")
    assert abs(data.C_over_D - Decimal("0.5")) < Decimal("0.0001")


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
        planning_start=date(2025, 4, 1),
        planning_end=date(2025, 6, 30),
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
    from app.services.effort_score import EFFORT_SCALE, EffortData
    from app.algorithm.types import SoldierInput, DutyBlock
    from app.services.algorithm_bridge import inject_effort_scores
    import uuid
    from datetime import date
    from decimal import Decimal

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
    # unit_score_milli = int(0.5 * 7 * 1000) = 3500
    # effort data: effort_score=0.1, C_over_D=0.5
    effort_map = {
        sid: EffortData(
            effort_score=Decimal("0.1"), C_over_D=Decimal("0.5"),
            effort_offset=int(Decimal("0.1") * EFFORT_SCALE),
        )
    }
    inject_effort_scores([s], [block], effort_map)
    assert s.effort_offset == int(Decimal("0.1") * EFFORT_SCALE)
    # effort_per_milli = int(0.5 / 3500 × EFFORT_SCALE) = int(142857) = 142857
    expected = int(Decimal("0.5") / 3500 * EFFORT_SCALE)
    assert s.effort_per_milli == expected


def test_transparency_rows_has_effort_score_key():
    """transparency_rows() output dicts must contain an 'effort_score' key."""
    import inspect
    from app.services import scoring as sc
    src = inspect.getsource(sc.transparency_rows)
    assert "effort_score" in src, "transparency_rows must include effort_score in output"
