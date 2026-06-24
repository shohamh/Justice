from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    PersonalConstraint,
)
from app.services.algorithm_bridge import (
    build_hierarchy_maps,
    load_duty_blocks,
    load_duty_blocks_from_shifts,
    load_existing_assignments,
    load_soldier_inputs,
)
from tests.helpers import create_node, create_soldier


def _published(session, shift, dt, loc, soldier, *, is_reserve=False, status="published"):
    a = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=shift.start_date, end_date=shift.end_date,
        status=status, is_reserve=is_reserve, duty_shift_id=shift.id,
    )
    session.add(a)
    session.flush()
    return a


def test_load_duty_blocks_from_shifts_skips_already_filled_slots(admin_session):
    """A re-run must only generate blocks for UNFILLED slots — not regenerate
    primary/reserve slots that already have a published or draft assignment."""
    dt = _duty_type(admin_session, name="שמירה_fill")
    loc = _location(admin_session, name="שער_fill")
    s = create_soldier(admin_session, personal_number="fill_soldier_1", role="soldier")
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2027, 7, 1), end_date=date(2027, 7, 2), required_count=3,
    )
    admin_session.add(shift)
    admin_session.flush()

    # No assignments yet -> full required_count of primary blocks.
    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert sum(1 for b in blocks if not b.is_reserve) == 3

    # 2 of 3 primary slots published -> only 1 primary block should be generated.
    _published(admin_session, shift, dt, loc, s)
    _published(admin_session, shift, dt, loc, s)
    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert sum(1 for b in blocks if not b.is_reserve) == 1

    # A pending draft counts as filling too -> all 3 primary slots occupied -> 0 primary blocks.
    _published(admin_session, shift, dt, loc, s, status="algorithm_draft")
    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert sum(1 for b in blocks if not b.is_reserve) == 0


def _duty_type(session, name="שמירה", score="1.00") -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _location(session, name="שער") -> DutyLocation:
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_load_soldier_inputs_basic(admin_session):
    s = create_soldier(admin_session, personal_number="alg_001", role="soldier")
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    ids = [si.id for si in inputs]
    assert s.id in ids


def test_load_soldier_inputs_excludes_left(admin_session):
    s = create_soldier(admin_session, personal_number="alg_002", role="soldier")
    s.left_at = date(2026, 5, 1)
    admin_session.commit()
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    ids = [si.id for si in inputs]
    assert s.id not in ids


def test_load_soldier_inputs_includes_approved_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="alg_003", role="soldier")
    pc = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        reason="חופשה",
        status="approved",
    )
    admin_session.add(pc)
    admin_session.commit()
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    my = next(si for si in inputs if si.id == s.id)
    assert (date(2026, 6, 10), date(2026, 6, 15)) in my.approved_constraint_dates


def test_load_soldier_inputs_excludes_pending_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="alg_004", role="soldier")
    pc = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        reason="רפואי",
        status="pending",
    )
    admin_session.add(pc)
    admin_session.commit()
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    my = next(si for si in inputs if si.id == s.id)
    assert my.approved_constraint_dates == []


def test_load_duty_blocks_generates_one_per_day_per_type(admin_session):
    dt1 = _duty_type(admin_session, name="שמירה_alg1")
    dt2 = _duty_type(admin_session, name="שמירה_alg2")
    loc = _location(admin_session, name="שער_alg")
    admin_session.commit()
    blocks = load_duty_blocks(
        admin_session,
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 3),
        duty_type_ids=[dt1.id, dt2.id],
        duty_location_id=loc.id,
    )
    # 3 days × 2 types = 6 blocks
    assert len(blocks) == 6
    dates = [b.start_date for b in blocks]
    assert date(2026, 6, 1) in dates
    assert date(2026, 6, 3) in dates


def test_load_duty_blocks_inactive_type_excluded(admin_session):
    dt_active = _duty_type(admin_session, name="שמירה_active_alg")
    dt_inactive = DutyType(name="שמירה_inactive_alg", score_per_day=Decimal("1.00"), active=False)
    admin_session.add(dt_inactive)
    admin_session.flush()
    loc = _location(admin_session, name="שער_alg2")
    admin_session.commit()
    blocks = load_duty_blocks(
        admin_session,
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 1),
        duty_type_ids=[dt_active.id, dt_inactive.id],
        duty_location_id=loc.id,
    )
    assert len(blocks) == 1
    assert blocks[0].duty_type_id == dt_active.id


def test_build_hierarchy_maps(admin_session):
    root = create_node(admin_session, level="department", name="dept_alg")
    child = create_node(admin_session, level="branch", name="branch_alg", parent=root)
    s = create_soldier(admin_session, personal_number="alg_hier_001", hierarchy_node_id=child.id)

    hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(admin_session)

    assert hier_parent[child.id] == root.id
    assert child.id in hier_children[root.id]
    assert soldier_node[s.id] == child.id
    assert s.id in node_soldiers[child.id]


def test_load_existing_assignments_carries_is_reserve(admin_session):
    s = create_soldier(admin_session, personal_number="alg_isres_001", role="soldier")
    dt = _duty_type(admin_session, name="שמירה_isres")
    loc = _location(admin_session, name="שער_isres")

    real_assignment = DutyAssignment(
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 10),
        status="published",
        is_reserve=False,
    )
    reserve_assignment = DutyAssignment(
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 11),
        end_date=date(2026, 6, 11),
        status="published",
        is_reserve=True,
    )
    admin_session.add(real_assignment)
    admin_session.add(reserve_assignment)
    admin_session.commit()

    existing = load_existing_assignments(
        admin_session,
        planning_start=date(2026, 6, 10),
        planning_end=date(2026, 6, 11),
        W=14,
    )

    by_start = {ea.start_date: ea for ea in existing if ea.soldier_id == s.id}
    assert by_start[date(2026, 6, 10)].is_reserve is False
    assert by_start[date(2026, 6, 11)].is_reserve is True
