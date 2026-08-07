from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


def _soldier(ineligible_block_ids: set[uuid.UUID] = frozenset()) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(), enrolled_at=date.today(), cumulative_score=Decimal("0"), active_days=1,
        weapon_ineligible_duty_block_ids=set(ineligible_block_ids),
    )


def test_hard_constraint_never_assigns_ineligible_soldier() -> None:
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date.today(), end_date=date.today(), score_per_day=Decimal("1.00"),
        required_range_type="laser",
    )
    ineligible = _soldier({block.id})
    eligible = _soldier()

    result = solve(
        [ineligible, eligible], [block], [], SolverSettings(time_limit_seconds=5, num_workers=1),
    )
    assigned_soldier_ids = {a.soldier_id for a in result.assignments}
    assert eligible.id in assigned_soldier_ids
    assert ineligible.id not in assigned_soldier_ids


def test_relaxed_setting_allows_ineligible_soldier_when_sole_candidate() -> None:
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date.today(), end_date=date.today(), score_per_day=Decimal("1.00"),
        required_range_type="laser",
    )
    ineligible = _soldier({block.id})

    result = solve(
        [ineligible], [block], [],
        SolverSettings(time_limit_seconds=5, num_workers=1, enforce_weapon_qualification=False),
    )
    assigned_soldier_ids = {a.soldier_id for a in result.assignments}
    assert ineligible.id in assigned_soldier_ids
