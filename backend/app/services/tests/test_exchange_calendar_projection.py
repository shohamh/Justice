"""Calendar snapshots use official persisted data and Israel wall times."""

from datetime import date, time, timedelta
from types import SimpleNamespace as Row
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    HierarchyNode,
    RangeAssignment,
    RangeEvent,
    RangeLocation,
    Soldier,
)
from app.services.exchange_calendar.projection import (
    ProjectionError,
    israel_local_datetime,
    project_source,
)

TODAY = date(2026, 9, 28)


class Rows:
    def __init__(self, *rows):
        self.rows = list(rows)

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self):
        self.objects = {}
        self.assignments = []
        self.range_assignments = []
        self.soldiers = []

    def add(self, model, **fields):
        row = Row(id=uuid4(), **fields)
        self.objects[(model, row.id)] = row
        if model is Soldier:
            self.soldiers.append(row)
        return row

    def get(self, model, key):
        return self.objects.get((model, key))

    def scalars(self, statement):
        model = statement.column_descriptions[0]["entity"]
        if model is DutyAssignment:
            return Rows(*self.assignments)
        if model is RangeAssignment:
            return Rows(*self.range_assignments)
        if model is Soldier:
            return Rows(*self.soldiers)
        raise AssertionError(model)


def soldier(db, name, email, node=None):
    return db.add(Soldier, full_name=name, email=email, hierarchy_node_id=node)


def shift_setup():
    db = FakeSession()
    dtype = db.add(DutyType, name="Guard", contact_name=None, contact_phone=None, instructions="Report early")
    location = db.add(DutyLocation, name="Gate", base="Base")
    shift = db.add(
        DutyShift, duty_type_id=dtype.id, duty_location_id=location.id,
        start_date=TODAY, end_date=TODAY, start_time="08:00", end_time="16:00",
        notes="Bring ID", status="active",
    )
    return db, dtype, shift


def assignment(db, shift, person, *, reserve=False, called_from=None, called_to=None, notes="private"):
    row = db.add(
        DutyAssignment, duty_shift_id=shift.id if shift else None,
        soldier_id=person.id, duty_type_id=shift.duty_type_id if shift else None,
        duty_location_id=shift.duty_location_id if shift else None,
        start_date=TODAY, end_date=TODAY, start_time="08:00", end_time="16:00",
        is_reserve=reserve, called_up_from=called_from, called_up_to=called_to,
        notes=notes, status="published",
    )
    db.assignments.append(row)
    return row


def range_setup(*, start="08:00", end="12:00"):
    db = FakeSession()
    location = db.add(RangeLocation, name="Range 7")
    event = db.add(
        RangeEvent, date=TODAY, range_type="live", range_location_id=location.id,
        start_time=start, end_time=end, status="planned", notes="Safety brief",
        arrival_instructions="Arrive 15 minutes early", contact_name=None,
        contact_phone=None, responsible_duty_manager_id=None,
    )
    return db, event


def test_shift_roster_roles_dedup_and_private_notes():
    db, _, shift = shift_setup()
    commander = soldier(db, "Commander", " COMMANDER@EXAMPLE.COM ")
    node = db.add(HierarchyNode, commander_id=commander.id)
    first = soldier(db, "First", " first@example.com ", node.id)
    second = soldier(db, "Second", "SECOND@example.com", node.id)
    reserve = soldier(db, "Reserve", "reserve@example.com", node.id)
    duplicate = soldier(db, "Duplicate", "FIRST@EXAMPLE.COM", node.id)
    assignment(db, shift, first)
    assignment(db, shift, second)
    assignment(db, shift, reserve, reserve=True)
    assignment(db, shift, duplicate, reserve=True)

    snap = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert snap.source_key == f"duty_shift:{shift.id}"
    assert snap.location == "Gate"
    assert [(a.email, a.required) for a in snap.attendees] == [
        ("commander@example.com", False), ("first@example.com", True),
        ("reserve@example.com", False), ("second@example.com", True),
    ]
    assert "Bring ID" in snap.body and "Report early" in snap.body
    assert "private" not in snap.body
    assert snap.start.tzinfo == ZoneInfo("Asia/Jerusalem")


def test_called_up_reserve_is_required_only_for_overlapping_dates():
    db, _, shift = shift_setup()
    reserve = soldier(db, "Reserve", "reserve@example.com")
    row = assignment(db, shift, reserve, reserve=True, called_from=TODAY, called_to=TODAY)
    snap = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert snap.attendees[0].required is True
    assert TODAY.isoformat() in snap.body
    row.called_up_from = TODAY + timedelta(days=1)
    row.called_up_to = TODAY + timedelta(days=2)
    snap = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert snap.attendees[0].required is False


def test_missing_email_is_reported_without_blocking_other_attendees():
    db, _, shift = shift_setup()
    assignment(db, shift, soldier(db, "No address", None))
    snap = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert snap.attendees == ()
    assert any(problem.code == "missing_email" for problem in snap.problems)


def test_unique_contact_is_invited_and_ambiguous_contact_falls_back_to_body():
    db, dtype, shift = shift_setup()
    dtype.contact_name = " Contact Person "
    dtype.contact_phone = "555"
    soldier(db, "contact  person", "contact@example.com")
    snap = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert any(a.email == "contact@example.com" and not a.required for a in snap.attendees)
    assert "555" not in snap.body
    soldier(db, "Contact Person", "other@example.com")
    snap = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert not any(a.email == "contact@example.com" for a in snap.attendees)
    assert "Contact Person" in snap.body and "555" in snap.body


def test_standalone_assignment_only_and_window_edges():
    db, _, shift = shift_setup()
    person = soldier(db, "Solo", "solo@example.com")
    row = assignment(db, None, person)
    row.duty_type_id = shift.duty_type_id
    row.duty_location_id = shift.duty_location_id
    assert project_source(db, "duty_assignment", row.id, today=TODAY).attendees[0].required
    row.duty_shift_id = shift.id
    assert project_source(db, "duty_assignment", row.id, today=TODAY) is None
    shift.start_date = date(2027, 9, 28)
    shift.end_date = shift.start_date
    assert project_source(db, "duty_shift", shift.id, today=TODAY) is not None
    shift.start_date = date(2027, 9, 29)
    shift.end_date = shift.start_date
    assert project_source(db, "duty_shift", shift.id, today=TODAY) is None


def test_range_manager_reserve_contact_and_all_day():
    db, event = range_setup(start=None, end=None)
    manager = soldier(db, "Manager", "manager@example.com")
    primary = soldier(db, "Primary", "primary@example.com")
    reserve = soldier(db, "Reserve", "reserve@example.com")
    event.responsible_duty_manager_id = manager.id
    event.contact_name = "Unknown contact"
    event.contact_phone = "123"
    db.range_assignments.extend([
        Row(range_event_id=event.id, soldier_id=primary.id, is_reserve=False, is_draft=False, note="secret"),
        Row(range_event_id=event.id, soldier_id=reserve.id, is_reserve=True, is_draft=False, note="secret"),
    ])
    snap = project_source(db, "range_event", event.id, today=TODAY)
    assert snap.all_day and snap.end.date() == TODAY + timedelta(days=1)
    assert snap.start.time() == time.min
    assert [(a.email, a.required) for a in snap.attendees] == [
        ("manager@example.com", False), ("primary@example.com", True),
        ("reserve@example.com", False),
    ]
    assert "Unknown contact" in snap.body and "123" in snap.body
    assert "Safety brief" in snap.body and "Arrive 15 minutes early" in snap.body
    assert "secret" not in snap.body


def test_range_one_sided_time_and_dst_gap_are_invalid():
    db, event = range_setup(start="08:00", end=None)
    with pytest.raises(ProjectionError):
        project_source(db, "range_event", event.id, today=TODAY)
    with pytest.raises(ProjectionError):
        israel_local_datetime(date(2026, 3, 27), "02:30")


def test_israel_repeated_hour_fold_zero_and_ews_mapping():
    repeated = israel_local_datetime(date(2026, 10, 25), "01:30")
    assert repeated.fold == 0
    assert repeated.tzinfo == ZoneInfo("Asia/Jerusalem")
    from exchangelib import EWSTimeZone
    assert EWSTimeZone.from_timezone(repeated.tzinfo).ms_id == "Israel Standard Time"


def test_content_hash_is_stable_until_visible_content_changes():
    db, _, shift = shift_setup()
    first = project_source(db, "duty_shift", shift.id, today=TODAY)
    assert first.content_hash == project_source(db, "duty_shift", shift.id, today=TODAY).content_hash
    shift.notes = "Changed"
    assert first.content_hash != project_source(db, "duty_shift", shift.id, today=TODAY).content_hash
