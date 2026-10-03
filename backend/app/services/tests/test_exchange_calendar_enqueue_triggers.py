"""Official calendar writes stay in the caller's database transaction."""

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

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
    israel_today,
)
from app.services.identity import canonical_identity
from app.services.shifts import create_shift, delete_shift, update_shift

TODAY = israel_today()
HORIZON = date(TODAY.year + 1, TODAY.month, min(TODAY.day, monthrange(TODAY.year + 1, TODAY.month)[1]))


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
        email=canonical_identity(email)[0],
        ad_username=canonical_identity(email)[1],
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
    edge = _shift(admin_session, start=HORIZON)
    future = _shift(admin_session, start=HORIZON + timedelta(days=1))
    past = _shift(admin_session, start=TODAY - timedelta(days=3), end=TODAY - timedelta(days=2))
    admin_session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=past.id, exchange_item_id="past-item", status="synced"))
    admin_session.flush()
    count = bootstrap_calendar_sources(
        admin_session, now=datetime.combine(TODAY, time(0, 30), ZoneInfo("Asia/Jerusalem")), batch_size=2
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
        admin_session, now=datetime.combine(TODAY, time(0, 30), ZoneInfo("Asia/Jerusalem")), batch_size=1,
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


def test_duty_type_fanout_only_visits_window_or_tracked_sources(admin_session: Session, monkeypatch):
    import app.services.exchange_calendar.triggers as triggers

    kind, place = _duty_labels(admin_session)

    def make_shift(start, end):
        shift = DutyShift(
            duty_type_id=kind.id, duty_location_id=place.id,
            start_date=start, end_date=end,
        )
        admin_session.add(shift)
        admin_session.flush()
        return shift

    old_unsynced = make_shift(TODAY - timedelta(days=30), TODAY - timedelta(days=29))
    old_synced = make_shift(TODAY - timedelta(days=20), TODAY - timedelta(days=19))
    ongoing = make_shift(TODAY - timedelta(days=1), TODAY + timedelta(days=1))
    beyond_horizon = make_shift(TODAY + timedelta(days=370), TODAY + timedelta(days=371))
    admin_session.add(ExchangeCalendarSyncItem(
        source_type="duty_shift", source_id=old_unsynced.id, status="queued",
    ))
    admin_session.add(ExchangeCalendarSyncItem(
        source_type="duty_shift", source_id=old_synced.id,
        exchange_item_id="existing-exchange-item", status="synced",
    ))
    admin_session.flush()
    visited = []
    original = triggers.enqueue_source_change

    def capture(session, source_type, source_id, **kwargs):
        visited.append(source_id)
        return original(session, source_type, source_id, **kwargs)

    monkeypatch.setattr(triggers, "enqueue_source_change", capture)
    assert triggers.enqueue_affected_by_duty_type(admin_session, kind.id, today=TODAY) == 2
    assert set(visited) == {old_synced.id, ongoing.id}
    assert _jobs(admin_session, old_unsynced.id) == []
    assert _jobs(admin_session, beyond_horizon.id) == []
    assert len(_jobs(admin_session, old_synced.id)) == 1
    assert len(_jobs(admin_session, ongoing.id)) == 1


def test_soldier_fanout_skips_old_untracked_assignments_and_ranges(admin_session: Session, monkeypatch):
    import app.services.exchange_calendar.triggers as triggers

    person = _soldier(admin_session)
    old_shift = _shift(admin_session, start=TODAY - timedelta(days=30))
    tracked_shift = _shift(admin_session, start=TODAY - timedelta(days=20))
    upcoming_shift = _shift(admin_session, start=TODAY + timedelta(days=2))
    for shift in (old_shift, tracked_shift, upcoming_shift):
        admin_session.add(DutyAssignment(
            soldier_id=person.id, duty_type_id=shift.duty_type_id,
            duty_location_id=shift.duty_location_id,
            start_date=shift.start_date, end_date=shift.end_date,
            duty_shift_id=shift.id,
        ))
    node = HierarchyNode(level="team", name=f"Team {uuid4()}", path_ids=[])
    place = RangeLocation(name=f"Range {uuid4()}")
    admin_session.add_all([node, place])
    admin_session.flush()
    events = []
    for event_date in (TODAY - timedelta(days=30), TODAY - timedelta(days=20), TODAY + timedelta(days=2)):
        event = RangeEvent(
            hierarchy_node_id=node.id, range_type="live", date=event_date,
            range_location_id=place.id, required_count=1,
            responsible_duty_manager_id=person.id,
        )
        admin_session.add(event)
        admin_session.flush()
        admin_session.add(RangeAssignment(range_event_id=event.id, soldier_id=person.id))
        events.append(event)
    admin_session.add_all([
        ExchangeCalendarSyncItem(source_type="duty_shift", source_id=tracked_shift.id,
                                 exchange_item_id="tracked-shift", status="synced"),
        ExchangeCalendarSyncItem(source_type="range_event", source_id=events[1].id,
                                 exchange_item_id="tracked-range", status="synced"),
    ])
    admin_session.flush()
    visited = []
    original = triggers.enqueue_source_change

    def capture(session, source_type, source_id, **kwargs):
        visited.append(source_id)
        return original(session, source_type, source_id, **kwargs)

    monkeypatch.setattr(triggers, "enqueue_source_change", capture)
    assert triggers.enqueue_affected_by_soldier(admin_session, person.id, today=TODAY) == 4
    assert set(visited) == {tracked_shift.id, upcoming_shift.id, events[1].id, events[2].id}
    assert old_shift.id not in visited
    assert events[0].id not in visited


def test_location_fanout_keeps_old_tracked_standalone_assignment(admin_session: Session, monkeypatch):
    import app.services.exchange_calendar.triggers as triggers

    kind, place = _duty_labels(admin_session)
    person = _soldier(admin_session)
    assignments = []
    for start in (TODAY - timedelta(days=30), TODAY - timedelta(days=20), TODAY + timedelta(days=2)):
        assignment = DutyAssignment(
            soldier_id=person.id, duty_type_id=kind.id, duty_location_id=place.id,
            start_date=start, end_date=start + timedelta(days=1),
        )
        admin_session.add(assignment)
        admin_session.flush()
        assignments.append(assignment)
    admin_session.add(ExchangeCalendarSyncItem(
        source_type="duty_assignment", source_id=assignments[1].id,
        exchange_item_id="tracked-assignment", status="synced",
    ))
    admin_session.flush()
    visited = []
    original = triggers.enqueue_source_change

    def capture(session, source_type, source_id, **kwargs):
        visited.append(source_id)
        return original(session, source_type, source_id, **kwargs)

    monkeypatch.setattr(triggers, "enqueue_source_change", capture)
    assert triggers.enqueue_affected_by_location(admin_session, place, today=TODAY) == 2
    assert set(visited) == {assignments[1].id, assignments[2].id}
    assert assignments[0].id not in visited


def _assignment_for(session, shift, person, *, standalone=False):
    row = DutyAssignment(
        soldier_id=person.id, duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id,
        start_date=shift.start_date, end_date=shift.end_date,
        duty_shift_id=None if standalone else shift.id,
    )
    session.add(row)
    session.flush()
    return row


def test_bulk_delete_route_queues_cancellation(admin_session, monkeypatch):
    from app.routes import shifts
    shift = _shift(admin_session)
    person = _soldier(admin_session)
    _assignment_for(admin_session, shift, person)
    source_id = shift.id
    monkeypatch.setattr(admin_session, "commit", admin_session.flush)
    monkeypatch.setattr(shifts, "authorize", lambda *args, **kwargs: None)
    shifts.bulk_delete_shifts(TODAY, TODAY + timedelta(days=2), admin_session, person)
    assert admin_session.get(DutyShift, source_id) is None
    assert len(_jobs(admin_session, source_id)) == 1
    assert _jobs(admin_session, source_id)[0].reason == "source_deleted"


def test_bulk_clear_route_queues_roster_update(admin_session, monkeypatch):
    from app.routes import shifts
    shift = _shift(admin_session)
    person = _soldier(admin_session)
    _assignment_for(admin_session, shift, person)
    monkeypatch.setattr(admin_session, "commit", admin_session.flush)
    monkeypatch.setattr(shifts, "authorize", lambda *args, **kwargs: None)
    shifts.bulk_clear_assignments(TODAY, TODAY + timedelta(days=2), admin_session, person)
    assert admin_session.get(DutyShift, shift.id) is not None
    assert len(_jobs(admin_session, shift.id)) == 1


def test_clear_all_route_queues_shared_and_standalone_sources(admin_session, monkeypatch):
    from app.routes import assignments
    shift = _shift(admin_session)
    person = _soldier(admin_session)
    shared = _assignment_for(admin_session, shift, person)
    solo = _assignment_for(admin_session, shift, person, standalone=True)
    monkeypatch.setattr(admin_session, "commit", admin_session.flush)
    monkeypatch.setattr(assignments, "authorize", lambda *args, **kwargs: None)
    assignments.clear_all_assignments(admin_session, person)
    assert shared.status == solo.status == "cancelled"
    assert len(_jobs(admin_session, shift.id)) == 1
    assert len(_jobs(admin_session, solo.id)) == 1


def test_parent_commander_fanout_includes_vacant_child_and_override(admin_session):
    from app.db.models import DutyDayOverride
    commander = _soldier(admin_session)
    parent = HierarchyNode(level="team", name=f"Parent {uuid4()}", path_ids=[], commander_id=commander.id)
    admin_session.add(parent)
    admin_session.flush()
    child = HierarchyNode(level="team", name=f"Child {uuid4()}", path_ids=[], parent_id=parent.id)
    admin_session.add(child)
    admin_session.flush()
    replacement = _soldier(admin_session, node=child.id)
    original = _soldier(admin_session)
    direct_shift, swapped_shift = _shift(admin_session), _shift(admin_session)
    _assignment_for(admin_session, direct_shift, replacement)
    row = _assignment_for(admin_session, swapped_shift, original)
    admin_session.add(DutyDayOverride(duty_assignment_id=row.id, date=TODAY,
                                     effective_soldier_id=replacement.id, reason="replacement"))
    admin_session.flush()
    enqueue_affected_by_soldier(admin_session, commander.id, today=TODAY)
    assert len(_jobs(admin_session, direct_shift.id)) == 1
    assert len(_jobs(admin_session, swapped_shift.id)) == 1


def test_parent_node_change_fanout_includes_vacant_children(admin_session):
    from app.services.exchange_calendar.triggers import enqueue_affected_by_hierarchy_node
    parent = HierarchyNode(level="team", name=f"Parent {uuid4()}", path_ids=[])
    admin_session.add(parent)
    admin_session.flush()
    child = HierarchyNode(level="team", name=f"Child {uuid4()}", path_ids=[], parent_id=parent.id)
    admin_session.add(child)
    admin_session.flush()
    person = _soldier(admin_session, node=child.id)
    shift = _shift(admin_session)
    _assignment_for(admin_session, shift, person)
    enqueue_affected_by_hierarchy_node(admin_session, parent.id, today=TODAY)
    assert len(_jobs(admin_session, shift.id)) == 1


def test_hr_contact_rename_and_email_change_queue_old_new_and_tracked_sources(admin_session):
    from types import SimpleNamespace

    from app.services.hr.mapping import HR_OWNED_FIELDS, MappedSoldierFields
    from app.services.hr.person_sync import _apply_existing_person
    initial_queue_count = admin_session.scalar(
        select(func.count()).select_from(ExchangeCalendarOutbox)
    )
    person = _soldier(admin_session)
    old_shift, new_shift = _shift(admin_session), _shift(admin_session)
    tracked = _shift(admin_session, start=TODAY - timedelta(days=30))
    _assignment_for(admin_session, tracked, person)
    admin_session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=tracked.id,
                                              exchange_item_id="tracked", status="synced"))
    admin_session.get(DutyType, old_shift.duty_type_id).contact_name = person.full_name
    admin_session.get(DutyType, new_shift.duty_type_id).contact_name = "New HR Name"
    admin_session.flush()
    mapped = MappedSoldierFields(**{
        **{name: getattr(person, name) for name in HR_OWNED_FIELDS},
        "full_name": "New HR Name", "email": "new@example.com",
    })
    profile = SimpleNamespace(soldier_id=person.id, overridden_fields=[])
    user = SimpleNamespace(model_dump=lambda **kwargs: {})
    _apply_existing_person(admin_session, profile, user, mapped)
    assert person.email == "new@example.com"
    for shift in (old_shift, new_shift, tracked):
        assert len(_jobs(admin_session, shift.id)) == 1
    admin_session.rollback()
    assert admin_session.scalar(select(func.count()).select_from(ExchangeCalendarOutbox)) == initial_queue_count


def test_bootstrap_claims_nearest_event_first_with_equal_queue_timestamps(admin_session):
    from datetime import UTC

    from sqlalchemy import delete

    from app.services.exchange_calendar.outbox import claim_next_job
    # Other route tests may commit their own jobs; claim ordering needs a clean
    # queue so it asserts only the three bootstrap events created here.
    admin_session.execute(delete(ExchangeCalendarOutbox))
    admin_session.expire_all()
    shifts = [_shift(admin_session, start=TODAY + timedelta(days=offset)) for offset in (20, 2, 9)]
    bootstrap_calendar_sources(admin_session, now=datetime.combine(TODAY, time(12), ZoneInfo("Asia/Jerusalem")))
    # Force UUID order to disagree with date order, as PostgreSQL transaction
    # timestamps already tie for every backfill enqueue.
    for i, shift in enumerate(shifts):
        job = _jobs(admin_session, shift.id)[0]
        job.id = __import__("uuid").UUID(int=i + 1)
    admin_session.flush()
    claimed = []
    for _ in range(3):
        job = claim_next_job(admin_session, worker_id="test", now=datetime.now(UTC) + timedelta(minutes=1))
        claimed.append(job.source_id)
    assert claimed == [shifts[1].id, shifts[2].id, shifts[0].id]
