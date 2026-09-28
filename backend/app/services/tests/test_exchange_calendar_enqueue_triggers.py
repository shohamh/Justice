"""Official calendar writes stay in the caller's database transaction."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ExchangeCalendarOutbox,
    ExchangeCalendarSyncItem,
    HierarchyNode,
    RangeAssignment,
    RangeEvent,
    RangeLocation,
    Soldier,
)
from app.services.exchange_calendar.triggers import (
    bootstrap_calendar_sources,
    enqueue_affected_by_soldier,
    enqueue_assignment_change,
    enqueue_source_change,
)
from app.services.shifts import create_shift, delete_shift, update_shift

TODAY = date(2026, 9, 28)


def _duty_labels(session: Session):
    kind = DutyType(name=f"Exchange {uuid4()}", score_per_day=Decimal("1"))
    place = DutyLocation(name=f"Gate {uuid4()}")
    session.add_all([kind, place])
    session.flush()
    return kind, place


def _shift(session: Session, *, start=TODAY, end=None):
    kind, place = _duty_labels(session)
    shift = DutyShift(
        duty_type_id=kind.id,
        duty_location_id=place.id,
        start_date=start,
        end_date=end or start + timedelta(days=1),
    )
    session.add(shift)
    session.flush()
    return shift


def _soldier(session: Session, *, email="soldier@example.com", node=None):
    person = Soldier(
        personal_number=str(uuid4()),
        full_name=f"Soldier {uuid4()}",
        password_hash="unused",
        email=email,
        hierarchy_node_id=node,
    )
    session.add(person)
    session.flush()
    return person


def _jobs(session: Session, source_id):
    return session.scalars(
        select(ExchangeCalendarOutbox).where(ExchangeCalendarOutbox.source_id == source_id)
    ).all()


def test_shift_create_edit_delete_coalesce_one_cancellation_job(admin_session: Session):
    kind, place = _duty_labels(admin_session)
    shift = create_shift(
        admin_session,
        duty_type_id=kind.id,
        duty_location_id=place.id,
        start_date=TODAY,
        end_date=TODAY + timedelta(days=1),
    )
    assert len(_jobs(admin_session, shift.id)) == 1
    update_shift(admin_session, shift=shift, notes="shared arrival instructions")
    assert len(_jobs(admin_session, shift.id)) == 1
    delete_shift(admin_session, shift=shift)
    admin_session.flush()
    jobs = _jobs(admin_session, shift.id)
    assert len(jobs) == 1
    assert jobs[0].reason == "source_deleted"


def test_assignment_change_queues_parent_or_standalone_once(admin_session: Session):
    shift = _shift(admin_session)
    person = _soldier(admin_session)
    row = DutyAssignment(
        soldier_id=person.id,
        duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id,
        start_date=shift.start_date,
        end_date=shift.end_date,
        duty_shift_id=shift.id,
    )
    admin_session.add(row)
    admin_session.flush()
    enqueue_assignment_change(admin_session, row)
    enqueue_assignment_change(admin_session, row)
    assert len(_jobs(admin_session, shift.id)) == 1
    assert _jobs(admin_session, row.id) == []
    row.duty_shift_id = None
    enqueue_assignment_change(admin_session, row)
    assert len(_jobs(admin_session, row.id)) == 1


def test_soldier_email_and_commander_fanout_coalesces_official_sources(admin_session: Session):
    commander = _soldier(admin_session, email="commander@example.com")
    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[], commander_id=commander.id)
    admin_session.add(node)
    admin_session.flush()
    person = _soldier(admin_session, node=node.id)
    shift = _shift(admin_session)
    admin_session.add(DutyAssignment(
        soldier_id=person.id, duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id,
        start_date=shift.start_date, end_date=shift.end_date, duty_shift_id=shift.id,
    ))
    location = RangeLocation(name=f"Range {uuid4()}")
    admin_session.add(location)
    admin_session.flush()
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type="live", date=TODAY,
        range_location_id=location.id, required_count=1,
    )
    admin_session.add(event)
    admin_session.flush()
    admin_session.add(RangeAssignment(range_event_id=event.id, soldier_id=person.id))
    admin_session.flush()
    enqueue_affected_by_soldier(admin_session, person.id, today=TODAY)
    enqueue_affected_by_soldier(admin_session, commander.id, today=TODAY)
    assert len(_jobs(admin_session, shift.id)) == 1
    assert len(_jobs(admin_session, event.id)) == 1


def test_bootstrap_uses_israel_horizon_and_keeps_existing_old_items(admin_session: Session):
    active = _shift(admin_session, start=TODAY - timedelta(days=1), end=TODAY + timedelta(days=1))
    edge = _shift(admin_session, start=date(2027, 9, 28))
    future = _shift(admin_session, start=date(2027, 9, 29))
    past = _shift(admin_session, start=TODAY - timedelta(days=3), end=TODAY - timedelta(days=2))
    admin_session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=past.id, status="synced"))
    admin_session.flush()
    count = bootstrap_calendar_sources(
        admin_session, now=datetime(2026, 9, 27, 22, 30, tzinfo=UTC), batch_size=2
    )
    assert count == 2
    assert len(_jobs(admin_session, active.id)) == 1
    assert len(_jobs(admin_session, edge.id)) == 1
    assert _jobs(admin_session, future.id) == []
    assert _jobs(admin_session, past.id) == []
    assert admin_session.scalar(select(func.count()).select_from(ExchangeCalendarSyncItem).where(
        ExchangeCalendarSyncItem.source_id == past.id
    )) == 1
    enqueue_source_change(admin_session, "duty_shift", past.id, reason="user_change")
    assert len(_jobs(admin_session, past.id)) == 1


def test_range_create_edit_cancel_queues_one_source_job(admin_session: Session):
    from app.db.models import RangeType
    from app.services.ranges import cancel_range_event, create_range_event, update_range_event

    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[])
    location = RangeLocation(name=f"Range {uuid4()}")
    admin_session.add_all([node, location])
    admin_session.flush()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=TODAY, range_location_id=location.id, required_count=1,
    )
    assert len(_jobs(admin_session, event.id)) == 1
    update_range_event(admin_session, event=event, notes="shared range notes")
    manager = _soldier(admin_session)
    update_range_event(
        admin_session, event=event, responsible_duty_manager_id=manager.id,
        arrival_instructions="Meet at the gate",
    )
    assert len(_jobs(admin_session, event.id)) == 1
    cancel_range_event(admin_session, event=event, reason="Cancelled")
    jobs = _jobs(admin_session, event.id)
    assert len(jobs) == 1
    assert jobs[0].reason == "cancelled"
    assert jobs[0].priority == 100  # USER_CHANGE


def test_duty_contact_and_location_fanout(admin_session: Session):
    from app.services.exchange_calendar.triggers import (
        enqueue_affected_by_duty_type,
        enqueue_affected_by_location,
    )

    shift = _shift(admin_session)
    kind = admin_session.get(DutyType, shift.duty_type_id)
    location = admin_session.get(DutyLocation, shift.duty_location_id)
    assert enqueue_affected_by_duty_type(admin_session, kind.id, today=TODAY) == 1
    assert enqueue_affected_by_location(admin_session, location, today=TODAY) == 1
    assert len(_jobs(admin_session, shift.id)) == 1

def test_profile_and_contact_metadata_writers_enqueue_existing_shift(admin_session: Session):
    from app.services.duty_config import update_duty_type, update_location
    from app.services.soldiers import update_soldier, update_soldier_profile

    shift = _shift(admin_session)
    person = _soldier(admin_session)
    admin_session.add(DutyAssignment(
        soldier_id=person.id, duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id, start_date=shift.start_date,
        end_date=shift.end_date, duty_shift_id=shift.id,
    ))
    admin_session.flush()
    update_soldier(admin_session, soldier=person, full_name="Updated Name", phone=None)
    update_soldier_profile(admin_session, soldier=person, fields={"email": "updated@example.com"}, actor_id=None)
    kind = admin_session.get(DutyType, shift.duty_type_id)
    place = admin_session.get(DutyLocation, shift.duty_location_id)
    update_duty_type(
        admin_session, duty_type=kind, name=None, score_per_day=None,
        description=None, contact_phone="123", actor_id=None,
    )
    update_location(admin_session, location=place, name="Updated Gate", base=None)
    assert len(_jobs(admin_session, shift.id)) == 1


def test_range_location_writer_enqueues_existing_range(admin_session: Session):
    from app.services.range_locations import update_range_location

    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[])
    place = RangeLocation(name=f"Old {uuid4()}")
    admin_session.add_all([node, place])
    admin_session.flush()
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type="live", date=TODAY,
        range_location_id=place.id, required_count=1,
    )
    admin_session.add(event)
    admin_session.flush()
    update_range_location(admin_session, location=place, name="New range")
    assert len(_jobs(admin_session, event.id)) == 1

def test_commander_writer_enqueues_subordinate_event(admin_session: Session):
    from app.services.hierarchy import set_commander

    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    person = _soldier(admin_session, node=node.id)
    commander = _soldier(admin_session)
    shift = _shift(admin_session)
    admin_session.add(DutyAssignment(
        soldier_id=person.id, duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id, start_date=shift.start_date,
        end_date=shift.end_date, duty_shift_id=shift.id,
    ))
    admin_session.flush()
    set_commander(admin_session, node_id=node.id, commander_id=commander.id)
    assert len(_jobs(admin_session, shift.id)) == 1

def test_draft_only_range_clear_does_not_publish_calendar(admin_session: Session):
    from app.db.models import RangeType
    from app.services.ranges import clear_range_assignments

    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[])
    place = RangeLocation(name=f"Range {uuid4()}")
    admin_session.add_all([node, place])
    admin_session.flush()
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.live, date=TODAY,
        range_location_id=place.id, required_count=1,
    )
    admin_session.add(event)
    admin_session.flush()
    person = _soldier(admin_session, node=node.id)
    admin_session.add(RangeAssignment(
        range_event_id=event.id, soldier_id=person.id, is_draft=True,
    ))
    admin_session.flush()
    clear_range_assignments(admin_session, event=event, reason="Reset proposal")
    assert _jobs(admin_session, event.id) == []

def test_bootstrap_orders_nearest_across_source_types(admin_session: Session, monkeypatch):
    import app.services.exchange_calendar.triggers as triggers

    shift = _shift(admin_session, start=TODAY + timedelta(days=5))
    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[])
    place = RangeLocation(name=f"Range {uuid4()}")
    admin_session.add_all([node, place])
    admin_session.flush()
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type="live", date=TODAY,
        range_location_id=place.id, required_count=1,
    )
    admin_session.add(event)
    admin_session.flush()
    calls = []
    original = triggers.enqueue_source

    def capture(session, kind, source_id, **kwargs):
        calls.append((kind, source_id))
        return original(session, kind, source_id, **kwargs)

    monkeypatch.setattr(triggers, "enqueue_source", capture)
    triggers.bootstrap_calendar_sources(
        admin_session, now=datetime(2026, 9, 27, 22, 30, tzinfo=UTC), batch_size=1,
    )
    assert calls == [("range_event", event.id), ("duty_shift", shift.id)]

def test_contact_name_rename_enqueues_old_and_new_matches(admin_session: Session):
    from app.services.soldiers import update_soldier

    person = _soldier(admin_session)
    old_shift = _shift(admin_session)
    new_shift = _shift(admin_session)
    admin_session.get(DutyType, old_shift.duty_type_id).contact_name = person.full_name
    admin_session.get(DutyType, new_shift.duty_type_id).contact_name = "New Contact"
    admin_session.flush()
    update_soldier(admin_session, soldier=person, full_name="New Contact", phone=None)
    assert len(_jobs(admin_session, old_shift.id)) == 1
    assert len(_jobs(admin_session, new_shift.id)) == 1
