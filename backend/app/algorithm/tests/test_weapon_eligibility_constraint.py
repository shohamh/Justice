from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.algorithm.solver import _eligible_pairs, solve
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


def _soldier(ineligible_block_ids: set[uuid.UUID] = frozenset()) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(), enrolled_at=date.today(), cumulative_score=Decimal("0"), active_days=1,
        weapon_ineligible_duty_block_ids=set(ineligible_block_ids),
    )


@pytest.mark.parametrize("reversed_order", [False, True], ids=["ineligible_first", "eligible_first"])
def test_hard_constraint_never_assigns_ineligible_soldier(reversed_order: bool) -> None:
    # Regression guard for a gap found during implementation: with CP-SAT's
    # default tie-breaking, [ineligible, eligible] ordering happened to avoid
    # the ineligible soldier even on a solver with the eligibility filter
    # removed, so a single fixed ordering isn't a reliable guard. Running both
    # orderings makes the assertion independent of tie-breaking coincidence.
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date.today(), end_date=date.today(), score_per_day=Decimal("1.00"),
        required_range_type="laser",
    )
    ineligible = _soldier({block.id})
    eligible = _soldier()
    soldiers = [eligible, ineligible] if reversed_order else [ineligible, eligible]

    result = solve(
        soldiers, [block], [], SolverSettings(time_limit_seconds=5, num_workers=1),
    )
    assigned_soldier_ids = {a.soldier_id for a in result.assignments}
    assert eligible.id in assigned_soldier_ids
    assert ineligible.id not in assigned_soldier_ids


def test_eligible_pairs_excludes_ineligible_soldier_only_when_enforced() -> None:
    # Deterministic, solver-independent guard directly against the eligibility
    # filter used by the decomposition path: doesn't depend on CP-SAT
    # tie-breaking at all.
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date.today(), end_date=date.today(), score_per_day=Decimal("1.00"),
        required_range_type="laser",
    )
    ineligible = _soldier({block.id})
    eligible = _soldier()
    soldiers = [ineligible, eligible]

    enforced_pairs = _eligible_pairs(
        soldiers, [block], SolverSettings(time_limit_seconds=5, num_workers=1),
    )
    assert (0, 0) not in enforced_pairs
    assert (0, 1) in enforced_pairs

    relaxed_pairs = _eligible_pairs(
        soldiers, [block],
        SolverSettings(time_limit_seconds=5, num_workers=1, enforce_weapon_qualification=False),
    )
    assert (0, 0) in relaxed_pairs
    assert (0, 1) in relaxed_pairs


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
