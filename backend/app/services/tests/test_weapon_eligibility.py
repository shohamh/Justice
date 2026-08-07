from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import (
    DutyType,
    RangeAssignment,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.ranges import add_range_assignment, create_range_event
from app.services.settings_loader import set_setting
from app.services.weapon_eligibility import bulk_ineligible_duty_blocks, compute_eligibility
from tests.helpers import create_node, create_range_location, create_soldier


def _make_weapon_eligible(session: Session, node_id) -> None:
    """`add_range_assignment` rejects soldiers who are structurally exempt from
    weapons (no requires_weapon=True DutyType in scope) -- see
    app.services.range_exemption.is_range_exempt. The brief's test bodies assume
    the soldier's node has a weapon-carrying duty type, matching the pattern used
    in tests/unit/test_ranges_service.py::test_add_range_assignment_success."""
    session.add(DutyType(
        name=f"weapon-duty-{node_id}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node_id],
    ))
    session.flush()


def test_none_required_type_is_always_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-001")
    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=None, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_current_qualification_covers_as_of_date(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-002")
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=10),
    )
    assert eligible is True
    assert reason is None


def test_expired_qualification_is_not_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-003")
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() - timedelta(days=1),
    ))
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=date.today()
    )
    assert eligible is False
    assert reason == "weapon_qualification"


def test_future_scheduled_range_grants_eligibility_on_and_after_its_date(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-1")
    _make_weapon_eligible(app_session, node.id)
    soldier = create_soldier(app_session, personal_number="we-004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    # Before the range: not yet eligible via this future assignment.
    too_early, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=4),
    )
    assert too_early is False

    # On/after the range date, within its projected validity window (180 days for laser).
    on_time, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=5),
    )
    assert on_time is True
    assert reason is None


def test_reserve_assignment_does_not_grant_eligibility(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-2")
    _make_weapon_eligible(app_session, node.id)
    soldier = create_soldier(app_session, personal_number="we-005", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1, reserve_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_pending_excusal_disqualifies_future_range_by_default(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-3")
    _make_weapon_eligible(app_session, node.id)
    soldier = create_soldier(app_session, personal_number="we-006", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, requested_by=soldier.id,
        reason="בדיקה", status=RangeExcusalStatus.pending,
    ))
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_pending_excusal_setting_off_keeps_future_range_eligible(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-4")
    _make_weapon_eligible(app_session, node.id)
    soldier = create_soldier(app_session, personal_number="we-007", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, requested_by=soldier.id,
        reason="בדיקה", status=RangeExcusalStatus.pending,
    ))
    set_setting(app_session, "weapon_qualification.pending_excusal_disqualifies", False, actor_id=None)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is True


def test_lower_tier_range_does_not_satisfy_higher_requirement(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-5")
    _make_weapon_eligible(app_session, node.id)
    soldier = create_soldier(app_session, personal_number="we-008", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False
    assert reason == "weapon_qualification"


def test_master_toggle_off_makes_everyone_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-009")
    set_setting(app_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_bulk_matches_single_soldier_result(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-6")
    _make_weapon_eligible(app_session, node.id)
    qualified = create_soldier(app_session, personal_number="we-010", hierarchy_node_id=node.id)
    unqualified = create_soldier(app_session, personal_number="we-011", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=qualified.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    block = DutyBlock(
        id=__import__("uuid").uuid4(), duty_type_id=__import__("uuid").uuid4(),
        duty_location_id=__import__("uuid").uuid4(),
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1),
        score_per_day=Decimal("1.00"), required_range_type=RangeType.laser,
    )
    result = bulk_ineligible_duty_blocks(
        app_session, soldier_ids=[qualified.id, unqualified.id], duties=[block]
    )
    assert qualified.id not in result or block.id not in result.get(qualified.id, set())
    assert block.id in result.get(unqualified.id, set())
