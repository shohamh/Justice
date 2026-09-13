from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.explain import build_explanations
from app.algorithm.types import Assignment, DutyBlock, SoldierInput


def test_build_explanations_basic() -> None:
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    duties = [DutyBlock(id=duty_id, duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duty_id, soldier_id=soldier_id)]
    result = build_explanations(
        soldiers=soldiers,
        duties=duties,
        assignments=assignments,
        global_before={"min_gap": 0, "norm_variance": 0},
        global_after={"min_gap": 5, "norm_variance": 1},
        solver_seed=42,
    )
    assert len(result.per_assignment) == 1
    assert result.per_assignment[0].duty_id == duty_id
    assert result.per_assignment[0].assigned_soldier_id == soldier_id
    assert any(
        c.soldier_id == soldier_id and not c.blocked
        for c in result.per_assignment[0].candidates
    )
    assert result.algorithm_version == "cp-sat-1.0"
    assert result.solver_seed == 42


def test_explain_overlap_blocking() -> None:
    """Soldier assigned to duty-1 should be blocked (overlap) for duty-2 on overlapping dates."""
    s_a = uuid4()
    s_b = uuid4()
    dt = uuid4()
    loc = uuid4()
    duty1 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 3),
                      score_per_day=Decimal("1"))
    duty2 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 2), end_date=date(2026, 6, 4),
                      score_per_day=Decimal("1"))
    soldiers = [
        SoldierInput(id=s_a, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=s_b, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
    ]
    # s_a → duty1, s_b → duty2; s_a should appear blocked (overlap) for duty2
    assignments = [Assignment(duty_id=duty1.id, soldier_id=s_a),
                   Assignment(duty_id=duty2.id, soldier_id=s_b)]
    result = build_explanations(soldiers, [duty1, duty2], assignments, {}, {}, 0)
    entry_d2 = next(e for e in result.per_assignment if e.duty_id == duty2.id)
    candidate_a = next(c for c in entry_d2.candidates if c.soldier_id == s_a)
    assert candidate_a.blocked
    assert "overlap" in candidate_a.blocking_constraints
    # s_b is the assigned soldier — not blocked for its own duty
    entry_d1 = next(e for e in result.per_assignment if e.duty_id == duty1.id)
    candidate_a_d1 = next(c for c in entry_d1.candidates if c.soldier_id == s_a)
    assert not candidate_a_d1.blocked


def test_explain_adjacent_duties_not_blocked() -> None:
    """Back-to-back duties (one's exclusive end_date == the other's start_date)
    don't actually overlap and must not be flagged as a conflict."""
    s_a = uuid4()
    s_b = uuid4()
    dt = uuid4()
    loc = uuid4()
    duty1 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                      score_per_day=Decimal("1"))
    duty2 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 2), end_date=date(2026, 6, 3),
                      score_per_day=Decimal("1"))
    soldiers = [
        SoldierInput(id=s_a, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=s_b, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
    ]
    assignments = [Assignment(duty_id=duty1.id, soldier_id=s_a),
                   Assignment(duty_id=duty2.id, soldier_id=s_b)]
    result = build_explanations(soldiers, [duty1, duty2], assignments, {}, {}, 0)
    entry_d2 = next(e for e in result.per_assignment if e.duty_id == duty2.id)
    candidate_a = next(c for c in entry_d2.candidates if c.soldier_id == s_a)
    assert not candidate_a.blocked
    assert "overlap" not in candidate_a.blocking_constraints


def test_explain_overlap_scan_finds_middle_and_skips_past_and_future_duties() -> None:
    """The overlap scan sorts a soldier's duties by start_date and breaks early
    once it passes the target's end_date. Regression-guard that early break
    against skipping a genuine overlap sitting between an already-ended past
    duty and a not-yet-reached future one, and against false-flagging either
    non-overlapping neighbor."""
    s_a = uuid4()
    s_b = uuid4()
    dt = uuid4()
    loc = uuid4()
    target = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                       start_date=date(2026, 6, 10), end_date=date(2026, 6, 12),
                       score_per_day=Decimal("1"))
    past_duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 3),
                          score_per_day=Decimal("1"))
    overlapping_duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                                 start_date=date(2026, 6, 5), end_date=date(2026, 6, 11),
                                 score_per_day=Decimal("1"))
    future_duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                            start_date=date(2026, 6, 20), end_date=date(2026, 6, 22),
                            score_per_day=Decimal("1"))
    soldiers = [
        SoldierInput(id=s_a, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=s_b, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
    ]
    assignments = [
        Assignment(duty_id=target.id, soldier_id=s_b),
        Assignment(duty_id=past_duty.id, soldier_id=s_a),
        Assignment(duty_id=overlapping_duty.id, soldier_id=s_a),
        Assignment(duty_id=future_duty.id, soldier_id=s_a),
    ]
    result = build_explanations(
        soldiers, [target, past_duty, overlapping_duty, future_duty], assignments, {}, {}, 0,
    )
    entry = next(e for e in result.per_assignment if e.duty_id == target.id)
    candidate_a = next(c for c in entry.candidates if c.soldier_id == s_a)
    assert candidate_a.blocked
    assert "overlap" in candidate_a.blocking_constraints


def test_explain_weapon_ineligible_candidate_blocked() -> None:
    """A soldier not weapon/range-qualified for this specific duty block (per
    SoldierInput.weapon_ineligible_duty_block_ids, populated by algorithm_bridge
    from bulk_ineligible_duty_blocks) is blocked with reason 'weapon_ineligible'."""
    soldier_a = uuid4()
    soldier_b = uuid4()
    duty_type = uuid4()
    duty = DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                     start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                     score_per_day=Decimal("1.00"))
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     weapon_ineligible_duty_block_ids={duty.id}),
    ]
    assignments = [Assignment(duty_id=duty.id, soldier_id=soldier_a)]
    result = build_explanations(soldiers, [duty], assignments, {}, {}, 0)
    entry = result.per_assignment[0]
    blocked = next(c for c in entry.candidates if c.soldier_id == soldier_b)
    unblocked = next(c for c in entry.candidates if c.soldier_id == soldier_a)
    assert blocked.blocked
    assert "weapon_ineligible" in blocked.blocking_constraints
    assert not unblocked.blocked


def test_explain_skips_reserve_duty_assignments() -> None:
    """Reserve-duty explanations are never persisted or read (persist_results
    only consults explanation_map for non-reserve blocks) -- building the full
    per-soldier candidate list for them is pure wasted work on large runs, so
    build_explanations must skip them entirely rather than compute-and-discard."""
    soldier_a = uuid4()
    soldier_b = uuid4()
    dt = uuid4()
    loc = uuid4()
    primary_duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                             start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                             score_per_day=Decimal("1"), is_reserve=False)
    reserve_duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                             start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                             score_per_day=Decimal("1"), is_reserve=True)
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100),
    ]
    assignments = [
        Assignment(duty_id=primary_duty.id, soldier_id=soldier_a),
        Assignment(duty_id=reserve_duty.id, soldier_id=soldier_b),
    ]
    result = build_explanations(soldiers, [primary_duty, reserve_duty], assignments, {}, {}, 0)
    assert len(result.per_assignment) == 1
    assert result.per_assignment[0].duty_id == primary_duty.id


def test_explain_blocked_candidate() -> None:
    soldier_a = uuid4()
    soldier_b = uuid4()
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     exempted_duty_type_ids={duty_type}),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=soldier_a)]
    result = build_explanations(soldiers, duties, assignments, {}, {}, 42)
    entry = result.per_assignment[0]
    blocked = [c for c in entry.candidates if c.blocked]
    unblocked = [c for c in entry.candidates if not c.blocked]
    assert len(blocked) == 1
    assert "exemption" in blocked[0].blocking_constraints
    assert len(unblocked) == 1
    assert unblocked[0].soldier_id == soldier_a
