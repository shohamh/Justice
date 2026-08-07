from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    PersonalConstraint,
    RangeAssignment,
    RangeType,
    SoldierRangeQualification,
)
from app.services.range_auto_assign import rank_candidates
from app.services.ranges import add_range_assignment, create_range_event
from tests.helpers import create_duty_location, create_node, create_range_location, create_soldier


def _weapon_duty_type(session: Session, *, node, name: str) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id])
    session.add(dt)
    session.flush()
    return dt


def _event(session: Session, *, required_count: int = 2, reserve_count: int = 1):
    node = create_node(session, level="branch", name="candidates")
    session.add(DutyType(name="weapon candidates", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(session, name="range").id,
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event


def test_ranks_available_soldiers_and_excludes_already_assigned(app_session: Session) -> None:
    node, event = _event(app_session)
    already = create_soldier(app_session, personal_number="cand-assigned", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=already.id, is_reserve=False)
    open_candidate = create_soldier(app_session, personal_number="cand-open", hierarchy_node_id=node.id)

    ranked = rank_candidates(app_session, event=event)

    ranked_ids = {c.soldier.id for c in ranked}
    assert already.id not in ranked_ids
    assert open_candidate.id in ranked_ids
    assert all(not c.blocked for c in ranked)


def test_marks_exempt_soldier_as_blocked_instead_of_excluding(app_session: Session) -> None:
    node, event = _event(app_session)
    soldier = create_soldier(app_session, personal_number="cand-exempt", hierarchy_node_id=node.id)

    from app.db.models import SoldierRangeQualification
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=event.date + timedelta(days=365), source_range_event_id=None, source_range_assignment_id=None,
    ))
    app_session.commit()

    ranked = rank_candidates(app_session, event=event)
    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is False
    assert mine.reason_code == "qualified"


def test_does_not_write_any_assignment_rows(app_session: Session) -> None:
    node, event = _event(app_session)
    create_soldier(app_session, personal_number="cand-readonly", hierarchy_node_id=node.id)

    rank_candidates(app_session, event=event)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    assert remaining == []


def test_candidates_exclude_soldier_outside_subtree(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א-outside")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ב-outside")
    _weapon_duty_type(app_session, node=node, name="weapon-a-outside")
    outsider = create_soldier(app_session, personal_number="6000001", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)

    assert outsider.id not in {c.soldier.id for c in ranked}


def test_marks_range_exempt_soldier_as_blocked(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה פטור")
    # No requires_weapon duty type eligible for this node -> soldier is structurally exempt.
    soldier = create_soldier(app_session, personal_number="6000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is True
    assert mine.blocked_reason == "exempt"


def test_marks_soldier_with_approved_constraint_as_blocked(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אילוץ")
    _weapon_duty_type(app_session, node=node, name="weapon-constraint")
    soldier = create_soldier(app_session, personal_number="6000004", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=event_date - timedelta(days=1),
        end_date=event_date + timedelta(days=1), reason="חופשה", status="approved",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is True
    assert mine.blocked_reason == "constraint"


def test_marks_soldier_on_duty_that_day_as_blocked(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בתורנות")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-on-duty")
    soldier = create_soldier(app_session, personal_number="6000005", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date, end_date=event_date + timedelta(days=1), status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is True
    assert mine.blocked_reason == "duty_assignment"


def test_does_not_block_soldier_when_duty_ends_on_event_date(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה סוף-תורנות-בלעדי")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-duty-exclusive-end")
    soldier = create_soldier(app_session, personal_number="6000008", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date - timedelta(days=1), end_date=event_date, status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is False


def test_marks_soldier_at_another_range_same_day_as_blocked(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מטווח-אחר")
    _weapon_duty_type(app_session, node=node, name="weapon-other-range")
    soldier = create_soldier(app_session, personal_number="6000006", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח אחר").id, required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=soldier.id, is_reserve=False)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is True
    assert mine.blocked_reason == "range_assignment"


def test_applies_all_eligibility_filters_independently_before_ranking(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה eligibility matrix")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה outside matrix")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-eligibility-matrix")
    duty_location = create_duty_location(app_session)
    event_date = date.today() + timedelta(days=5)
    eligible = create_soldier(app_session, personal_number="6000010", hierarchy_node_id=node.id)
    outside_subtree = create_soldier(app_session, personal_number="6000011", hierarchy_node_id=other_node.id)
    constrained = create_soldier(app_session, personal_number="6000012", hierarchy_node_id=node.id)
    on_duty = create_soldier(app_session, personal_number="6000013", hierarchy_node_id=node.id)
    at_another_range = create_soldier(app_session, personal_number="6000014", hierarchy_node_id=node.id)
    app_session.add(PersonalConstraint(
        soldier_id=constrained.id, start_date=event_date, end_date=event_date,
        reason="approved leave", status="approved",
    ))
    app_session.add(DutyAssignment(
        soldier_id=on_duty.id, duty_type_id=weapon_dt.id, duty_location_id=duty_location.id,
        start_date=event_date, end_date=event_date + timedelta(days=1), status="published",
    ))
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, range_location_id=create_range_location(app_session, name="another range").id, required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=at_another_range.id, is_reserve=False)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)
    ranked_ids = {c.soldier.id for c in ranked}

    assert outside_subtree.id not in ranked_ids
    by_id = {c.soldier.id: c for c in ranked}
    assert by_id[eligible.id].blocked is False
    assert by_id[constrained.id].blocked is True
    assert by_id[constrained.id].blocked_reason == "constraint"
    assert by_id[on_duty.id].blocked is True
    assert by_id[on_duty.id].blocked_reason == "duty_assignment"
    assert by_id[at_another_range.id].blocked is True
    assert by_id[at_another_range.id].blocked_reason == "range_assignment"


def test_tier_a_sorts_before_tier_b_before_tier_c(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה שכבות")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-tiers")
    event_date = date.today() + timedelta(days=5)

    tier_c_soldier = create_soldier(app_session, personal_number="6100001", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=tier_c_soldier.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=30),
    ))
    tier_b_soldier = create_soldier(app_session, personal_number="6100002", hierarchy_node_id=node.id)
    tier_a_soldier = create_soldier(app_session, personal_number="6100003", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=tier_a_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1), status="published",
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
    )

    ranked = rank_candidates(app_session, event=event)

    order = [c.soldier.id for c in ranked]
    assert order == [tier_a_soldier.id, tier_b_soldier.id, tier_c_soldier.id]


def test_tier_a_orders_by_earliest_duty_start(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-א")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-tier-a-order")
    event_date = date.today() + timedelta(days=5)

    later_soldier = create_soldier(app_session, personal_number="6200001", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=later_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=10), status="published",
    ))
    sooner_soldier = create_soldier(app_session, personal_number="6200002", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=sooner_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=2), end_date=date.today() + timedelta(days=2), status="published",
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
    )

    ranked = rank_candidates(app_session, event=event)

    order = [c.soldier.id for c in ranked]
    assert order == [sooner_soldier.id, later_soldier.id]


def test_tier_c_orders_by_soonest_expiring_qualification(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-ג")
    _weapon_duty_type(app_session, node=node, name="weapon-tier-c-order")
    event_date = date.today() + timedelta(days=5)

    expires_later = create_soldier(app_session, personal_number="6300001", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=expires_later.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=100),
    ))
    expires_sooner = create_soldier(app_session, personal_number="6300002", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=expires_sooner.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=10),
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
    )

    ranked = rank_candidates(app_session, event=event)

    order = [c.soldier.id for c in ranked]
    assert order == [expires_sooner.id, expires_later.id]


def test_qualification_at_higher_range_type_counts_as_tier_c(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה איכות-גבוהה")
    _weapon_duty_type(app_session, node=node, name="weapon-higher-qual")
    event_date = date.today() + timedelta(days=5)

    soldier = create_soldier(app_session, personal_number="6400001", hierarchy_node_id=node.id)
    # Qualified at "live" (higher than the event's "laser") -> still Tier C for a laser event.
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.live, valid_until=event_date + timedelta(days=10),
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "qualified"
    assert mine.blocked is False


def test_reason_code_available_and_balanced_when_no_qualification_or_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת סיבת שיבוץ")
    _weapon_duty_type(app_session, node=node, name="תורנות נשק סיבת שיבוץ")
    soldier = create_soldier(app_session, personal_number="7010001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "available_and_balanced"


def test_reason_code_weapon_duty_priority_for_future_weapon_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת עדיפות נשק")
    soldier = create_soldier(app_session, personal_number="7010004", hierarchy_node_id=node.id)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="תורנות נשק עדיפות")
    location = create_duty_location(app_session)
    future_duty_date = date.today() + timedelta(days=2)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=future_duty_date, end_date=future_duty_date, status="published",
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "weapon_duty_priority"
