from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from threading import Event, Thread

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    DutyAssignment,
    DutyType,
    Notification,
    NotificationType,
    PersonalConstraint,
    RangeEventStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services import range_auto_assign as range_auto_assign_service
from app.services.range_auto_assign import (
    confirm_all_drafts,
    confirm_draft_assignment,
    propose_range_assignments,
)
from app.services.ranges import RangeValidationError, add_range_assignment, create_range_event
from tests.helpers import create_node, create_soldier


def _weapon_duty_type(session: Session, *, node, name: str) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id])
    session.add(dt)
    session.flush()
    return dt


def test_candidate_pool_excludes_soldier_outside_subtree(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א-outside")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ב-outside")
    _weapon_duty_type(app_session, node=node, name="weapon-a-outside")
    outsider = create_soldier(app_session, personal_number="6000001", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert outsider.id not in {a.soldier_id for a in created}
    assert shortfall == 1


def test_candidate_pool_excludes_already_assigned(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה כבר-משובץ")
    _weapon_duty_type(app_session, node=node, name="weapon-already-assigned")
    soldier = create_soldier(app_session, personal_number="6000002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert created == []
    assert shortfall == 0


def test_candidate_pool_excludes_range_exempt_soldier(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה פטור")
    # No requires_weapon duty type eligible for this node -> soldier is structurally exempt.
    soldier = create_soldier(app_session, personal_number="6000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}


def test_candidate_pool_excludes_approved_personal_constraint(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אילוץ")
    _weapon_duty_type(app_session, node=node, name="weapon-constraint")
    soldier = create_soldier(app_session, personal_number="6000004", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=event_date - timedelta(days=1),
        end_date=event_date + timedelta(days=1), reason="חופשה", status="approved",
    ))
    app_session.flush()

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}
    assert shortfall == 1


def test_candidate_pool_excludes_soldier_on_duty_that_day(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בתורנות")
    location = None
    from tests.helpers import create_duty_location
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-on-duty")
    soldier = create_soldier(app_session, personal_number="6000005", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date, end_date=event_date + timedelta(days=1), status="published",
    ))
    app_session.flush()

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}


def test_candidate_pool_includes_soldier_when_duty_ends_on_event_date(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה סוף-תורנות-בלעדי")
    from tests.helpers import create_duty_location

    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-duty-exclusive-end")
    soldier = create_soldier(app_session, personal_number="6000008", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date - timedelta(days=1), end_date=event_date, status="published",
    ))
    app_session.flush()

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [assignment.soldier_id for assignment in created] == [soldier.id]
    assert shortfall == 0


def test_candidate_pool_excludes_soldier_at_another_range_same_day(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מטווח-אחר")
    _weapon_duty_type(app_session, node=node, name="weapon-other-range")
    soldier = create_soldier(app_session, personal_number="6000006", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, location="מטווח אחר", required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=soldier.id, is_reserve=False)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}



def test_candidate_pool_applies_all_assignment_eligibility_filters_before_ranking(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה eligibility matrix")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה outside matrix")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-eligibility-matrix")
    from tests.helpers import create_duty_location

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
        event_date=event_date, location="another range", required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=at_another_range.id, is_reserve=False)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [assignment.soldier_id for assignment in created] == [eligible.id]
    assert shortfall == 0
    assert outside_subtree.id not in {assignment.soldier_id for assignment in created}


def test_auto_assign_counts_existing_primary_and_reserve_assignments_separately(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה existing quotas")
    _weapon_duty_type(app_session, node=node, name="weapon-existing-quotas")
    event_date = date.today() + timedelta(days=5)
    existing_primary = create_soldier(app_session, personal_number="6000020", hierarchy_node_id=node.id)
    existing_reserve = create_soldier(app_session, personal_number="6000021", hierarchy_node_id=node.id)
    next_primary = create_soldier(app_session, personal_number="6000022", hierarchy_node_id=node.id)
    next_reserve = create_soldier(app_session, personal_number="6000023", hierarchy_node_id=node.id)
    app_session.add_all([
        SoldierRangeQualification(
            soldier_id=next_primary.id, range_type=RangeType.laser,
            valid_until=event_date + timedelta(days=5),
        ),
        SoldierRangeQualification(
            soldier_id=next_reserve.id, range_type=RangeType.laser,
            valid_until=event_date + timedelta(days=10),
        ),
    ])
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=2, reserve_count=2,
    )
    add_range_assignment(app_session, event=event, soldier_id=existing_primary.id, is_reserve=False)
    add_range_assignment(app_session, event=event, soldier_id=existing_reserve.id, is_reserve=True)

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [(assignment.soldier_id, assignment.is_reserve, assignment.is_draft) for assignment in created] == [
        (next_primary.id, False, True),
        (next_reserve.id, True, True),
    ]
    assert shortfall == 0

def test_tier_a_sorts_before_tier_b_before_tier_c(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה שכבות")
    location = None
    from tests.helpers import create_duty_location
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
        event_date=event_date, location="מטווח", required_count=3,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    order = [a.soldier_id for a in created]
    assert order == [tier_a_soldier.id, tier_b_soldier.id, tier_c_soldier.id]
    assert shortfall == 0


def test_tier_a_orders_by_earliest_duty_start(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-א")
    location = None
    from tests.helpers import create_duty_location
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
        event_date=event_date, location="מטווח", required_count=2,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [sooner_soldier.id, later_soldier.id]


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
        event_date=event_date, location="מטווח", required_count=2,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [expires_sooner.id, expires_later.id]


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
        event_date=event_date, location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [soldier.id]


def test_fill_respects_primary_then_reserve_counts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מילוי")
    _weapon_duty_type(app_session, node=node, name="weapon-fill")
    event_date = date.today() + timedelta(days=5)
    for i in range(3):
        create_soldier(
            app_session,
            personal_number=f"650000{i}",
            hierarchy_node_id=node.id,
        )
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=2, reserve_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert shortfall == 0
    assert sum(1 for a in created if not a.is_reserve) == 2
    assert sum(1 for a in created if a.is_reserve) == 1


def test_partial_fill_reports_shortfall(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מחסור")
    _weapon_duty_type(app_session, node=node, name="weapon-shortfall")
    event_date = date.today() + timedelta(days=5)
    create_soldier(app_session, personal_number="6600001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=3,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert len(created) == 1
    assert shortfall == 2


def test_created_drafts_have_is_draft_true(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טיוטה")
    _weapon_duty_type(app_session, node=node, name="weapon-draft")
    soldier = create_soldier(app_session, personal_number="6700001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert all(a.is_draft for a in created)
    assignment_notifications = app_session.query(Notification).filter(
        Notification.soldier_id == soldier.id,
        Notification.type == NotificationType.assignment_created,
    ).count()
    assert assignment_notifications == 0


def test_auto_assign_only_fills_remaining_slots(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה חלקי-כבר-משובץ")
    _weapon_duty_type(app_session, node=node, name="weapon-partial-existing")
    already = create_soldier(app_session, personal_number="6800001", hierarchy_node_id=node.id)
    candidate = create_soldier(app_session, personal_number="6800002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    add_range_assignment(app_session, event=event, soldier_id=already.id, is_reserve=False)

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [candidate.id]
    assert shortfall == 0


def test_propose_rejects_non_planned_event(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בוטל")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    from app.services.ranges import cancel_range_event
    cancel_range_event(app_session, event=event, reason="test cancellation")

    with pytest.raises(RangeValidationError):
        propose_range_assignments(app_session, event=event)


def test_propose_waits_for_date_lock_and_revalidates_event_before_reading_candidates(
    app_session: Session, app_engine,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה נעילת-מטווח")
    _weapon_duty_type(app_session, node=node, name="weapon-date-lock")
    create_soldier(app_session, personal_number="6800003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    event_id = event.id
    event_date = event.date
    loaded = Event()
    finished = Event()
    errors: list[str] = []
    created_counts: list[int] = []
    SessionLocal = sessionmaker(bind=app_engine, expire_on_commit=False)

    def run_auto_assign() -> None:
        with SessionLocal() as worker_session:
            worker_event = worker_session.get(range_auto_assign_service.RangeEvent, event_id)
            assert worker_event is not None
            loaded.set()
            try:
                created, _shortfall = propose_range_assignments(
                    worker_session, event=worker_event
                )
                created_counts.append(len(created))
            except Exception as exc:  # captured for assertion in the main test thread
                errors.append(str(exc))
            finally:
                finished.set()

    with SessionLocal() as lock_session:
        lock_session.execute(
            select(func.pg_advisory_xact_lock(0x52414E47, event_date.toordinal()))
        )
        locked_event = lock_session.get(range_auto_assign_service.RangeEvent, event_id)
        assert locked_event is not None
        worker = Thread(target=run_auto_assign)
        worker.start()
        assert loaded.wait(timeout=5)
        was_blocked = not finished.wait(timeout=0.2)
        locked_event.status = RangeEventStatus.cancelled
        lock_session.commit()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert was_blocked
    assert errors == ["event_not_planned"]
    assert created_counts == []
    assignment_count = app_session.query(range_auto_assign_service.RangeAssignment).filter(
        range_auto_assign_service.RangeAssignment.range_event_id == event_id
    ).count()
    assert assignment_count == 0


def test_confirm_draft_assignment_flips_is_draft_and_notifies(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אישור")
    _weapon_duty_type(app_session, node=node, name="weapon-confirm")
    soldier = create_soldier(app_session, personal_number="6900001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    created, _ = propose_range_assignments(app_session, event=event)
    draft = created[0]

    confirmed = confirm_draft_assignment(app_session, assignment=draft, actor_id=soldier.id)

    assert confirmed.is_draft is False
    notification = app_session.query(Notification).filter(
        Notification.soldier_id == confirmed.soldier_id,
        Notification.type == NotificationType.range_assignment_confirmed,
    ).one_or_none()
    assert notification is not None


def test_confirm_draft_assignment_rejects_non_draft(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה לא-טיוטה")
    _weapon_duty_type(app_session, node=node, name="weapon-not-draft")
    soldier = create_soldier(app_session, personal_number="6900002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    manual = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    with pytest.raises(RangeValidationError):
        confirm_draft_assignment(app_session, assignment=manual, actor_id=soldier.id)


def test_confirm_all_drafts_confirms_every_draft_with_one_commit_and_one_notification_each(
    app_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אישור-הכל")
    _weapon_duty_type(app_session, node=node, name="weapon-confirm-all")
    create_soldier(app_session, personal_number="6900003", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="6900004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    propose_range_assignments(app_session, event=event)
    real_commit = app_session.commit
    commit_count = 0

    def counting_commit() -> None:
        nonlocal commit_count
        commit_count += 1
        real_commit()

    monkeypatch.setattr(app_session, "commit", counting_commit)

    confirmed = confirm_all_drafts(app_session, event=event, actor_id=None)

    assert len(confirmed) == 2
    assert all(a.is_draft is False for a in confirmed)
    assert commit_count == 1
    notification_count = app_session.query(Notification).filter(
        Notification.type == NotificationType.range_assignment_confirmed,
        Notification.reference_id.in_([assignment.id for assignment in confirmed]),
    ).count()
    assert notification_count == 2


def test_confirm_all_drafts_rolls_back_everything_when_mid_batch_notification_fails(
    app_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אישור-הכל-חזרה")
    _weapon_duty_type(app_session, node=node, name="weapon-confirm-all-rollback")
    create_soldier(app_session, personal_number="6900009", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="6900010", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    drafts, _ = propose_range_assignments(app_session, event=event)
    draft_ids = [assignment.id for assignment in drafts]
    real_create_notification = range_auto_assign_service.create_notification
    notification_attempts = 0

    def fail_second_notification(*args, **kwargs):
        nonlocal notification_attempts
        notification_attempts += 1
        if notification_attempts == 2:
            raise RuntimeError("notification failure")
        return real_create_notification(*args, **kwargs)

    monkeypatch.setattr(
        range_auto_assign_service,
        "create_notification",
        fail_second_notification,
    )

    with pytest.raises(RuntimeError, match="notification failure"):
        confirm_all_drafts(app_session, event=event, actor_id=None)

    app_session.rollback()
    persisted_drafts = app_session.query(range_auto_assign_service.RangeAssignment).filter(
        range_auto_assign_service.RangeAssignment.id.in_(draft_ids)
    ).all()
    assert len(persisted_drafts) == 2
    assert all(assignment.is_draft for assignment in persisted_drafts)
    notification_count = app_session.query(Notification).filter(
        Notification.type == NotificationType.range_assignment_confirmed,
        Notification.reference_id.in_(draft_ids),
    ).count()
    assert notification_count == 0


def test_confirm_all_drafts_leaves_non_draft_assignments_untouched(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מעורב")
    _weapon_duty_type(app_session, node=node, name="weapon-mixed")
    manual_soldier = create_soldier(app_session, personal_number="6900005", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="6900006", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    manual = add_range_assignment(app_session, event=event, soldier_id=manual_soldier.id, is_reserve=False)
    propose_range_assignments(app_session, event=event)

    confirm_all_drafts(app_session, event=event, actor_id=None)

    app_session.refresh(manual)
    assert manual.is_draft is False  # was already False, untouched


def test_rejecting_a_draft_deletes_the_row_and_reopens_the_slot(app_session: Session) -> None:
    from app.services.ranges import remove_range_assignment

    node = create_node(app_session, level="פלוגה", name="פלוגה דחייה")
    _weapon_duty_type(app_session, node=node, name="weapon-reject")
    create_soldier(app_session, personal_number="6900007", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    created, _ = propose_range_assignments(app_session, event=event)
    draft = created[0]

    remove_range_assignment(app_session, assignment=draft)

    created_again, shortfall = propose_range_assignments(app_session, event=event)
    assert len(created_again) == 1
    assert shortfall == 0

def test_confirm_draft_rejects_event_not_planned(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בוטלה")
    _weapon_duty_type(app_session, node=node, name="weapon-cancelled-confirm")
    create_soldier(app_session, personal_number="6900008", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    created, _ = propose_range_assignments(app_session, event=event)
    draft = created[0]
    from app.services.ranges import cancel_range_event
    cancel_range_event(app_session, event=event, reason="test cancellation")

    with pytest.raises(RangeValidationError):
        confirm_draft_assignment(app_session, assignment=draft)
