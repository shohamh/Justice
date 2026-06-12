# backend/tests/test_model_effort.py
"""Verify the CP-SAT model uses effort-based objective when effort fields are set."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.algorithm.model import build_model
from app.algorithm.types import (
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)
from app.algorithm.solver import solve


def _soldier(score: Decimal, active_days: int, effort_offset: int, effort_per_milli: int, enrolled: date | None = None) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=enrolled or date(2024, 1, 1),
        cumulative_score=score,
        active_days=active_days,
        effort_offset=effort_offset,
        effort_per_milli=effort_per_milli,
    )


def _block(start: date, end: date, score: Decimal = Decimal("0.5")) -> DutyBlock:
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=start, end_date=end,
        score_per_day=score,
    )


def test_new_soldier_gets_duties_over_veteran():
    """
    Veteran has high effort_offset (100M). New soldier has effort_offset=0.
    With 2 duties and 2 soldiers, the new soldier should get at least 1 duty
    because assigning to them doesn't raise max_effort (they're far below veteran).
    """
    veteran = _soldier(
        score=Decimal("50"), active_days=1000,
        effort_offset=100_000_000,  # already high historical effort
        effort_per_milli=100,       # each duty only raises veteran effort by a little
    )
    newbie = _soldier(
        score=Decimal("0"), active_days=90,
        effort_offset=0,
        effort_per_milli=1000,  # each duty raises newbie effort by more (fewer quarters)
    )
    dt_id = uuid.uuid4()
    loc_id = uuid.uuid4()
    veteran.exempted_duty_type_ids = set()
    newbie.exempted_duty_type_ids = set()

    duties = [
        DutyBlock(id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=loc_id,
                  start_date=date(2026, 7, 1), end_date=date(2026, 7, 1), score_per_day=Decimal("0.5")),
        DutyBlock(id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=loc_id,
                  start_date=date(2026, 7, 2), end_date=date(2026, 7, 2), score_per_day=Decimal("0.5")),
    ]
    settings = SolverSettings(T=7, Wt=14, Wr=28, alpha=Decimal("1.0"), time_limit_seconds=10)
    result = solve([veteran, newbie], duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    new_count = sum(1 for a in result.assignments if a.soldier_id == newbie.id)
    assert new_count >= 1, f"New soldier got {new_count} duties, expected >=1"


def test_model_builds_without_error_with_zero_effort():
    """Model must build and solve even when all effort fields are 0 (fallback path)."""
    dt_id = uuid.uuid4()
    loc_id = uuid.uuid4()
    soldiers = [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     effort_offset=0, effort_per_milli=0)
        for _ in range(3)
    ]
    duties = [
        DutyBlock(id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=loc_id,
                  start_date=date(2026, 7, i), end_date=date(2026, 7, i),
                  score_per_day=Decimal("0.5"))
        for i in range(1, 4)
    ]
    settings = SolverSettings(T=7, Wt=14, Wr=28, alpha=Decimal("1.0"), time_limit_seconds=10)
    result = solve(soldiers, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 3
