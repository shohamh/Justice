"""Tests for app.services.duty_history.get_duty_history."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
)
from app.services.duty_history import get_duty_history
from tests.helpers import create_soldier


def _uid() -> str:
    """Return a short unique suffix for use in names/personal numbers."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Shared fixtures — each invocation gets unique identifiers to avoid
# unique-constraint violations across tests (the DB is shared for the session).
# ---------------------------------------------------------------------------


@pytest.fixture()
def soldier(admin_session):
    return create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")


@pytest.fixture()
def duty_type(admin_session):
    dt = DutyType(name=f"שמירה_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    admin_session.flush()
    return dt


@pytest.fixture()
def location(admin_session):
    loc = DutyLocation(name=f"שער_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    return loc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_history(admin_session):
    """A brand-new soldier with no data produces an empty event list."""
    s = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    events = get_duty_history(admin_session, s.id)
    assert events == []


def test_assignment_appears(admin_session, soldier, duty_type, location):
    """A published DutyAssignment produces a single 'assignment' event."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "assignment"
    assert ev.date == "2026-06-10"
    assert duty_type.name in ev.title
    assert location.name in ev.title
    assert ev.status == "published"


def test_cancellation_appears(admin_session, soldier, duty_type, location):
    """A cancelled DutyAssignment produces a 'cancellation' event."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="cancelled",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "cancellation"
    assert ev.status == "cancelled"


def test_call_up_appears(admin_session, soldier, duty_type, location):
    """An assignment with called_up_from produces both a 'call_up' and an 'assignment' event."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="published",
        called_up_from=date(2026, 6, 8),
        called_up_to=date(2026, 6, 9),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    event_types = {ev.event_type for ev in events}

    assert "call_up" in event_types
    assert "assignment" in event_types
    assert len(events) == 2

    call_up_ev = next(ev for ev in events if ev.event_type == "call_up")
    assert call_up_ev.date == "2026-06-08"
    assert call_up_ev.end_date == "2026-06-09"

    assignment_event = next(e for e in events if e.event_type == "assignment")
    assert assignment_event.date == "2026-06-10"


def test_dismissal_appears(admin_session, soldier, duty_type, location):
    """A DutyDismissal linked to an assignment produces a 'dismissal' event."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    d = DutyDismissal(
        duty_assignment_id=a.id,
        dismissed_from=date(2026, 6, 11),
        dismissed_to=date(2026, 6, 12),
        reason="חופש",
    )
    admin_session.add(d)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    event_types = [ev.event_type for ev in events]

    assert "dismissal" in event_types
    dismissal_ev = next(ev for ev in events if ev.event_type == "dismissal")
    assert dismissal_ev.date == "2026-06-11"
    assert dismissal_ev.end_date == "2026-06-12"
    assert dismissal_ev.description == "חופש"


def test_exemption_request_appears(admin_session, soldier):
    """An ExemptionRequest produces an 'exemption_request' event."""
    et = ExemptionType(name=f"פציעה_{_uid()}", is_global=True)
    admin_session.add(et)
    admin_session.flush()

    er = ExemptionRequest(
        soldier_id=soldier.id,
        exemption_type_id=et.id,
        start_date=date(2026, 6, 15),
        reason="נפצעתי",
    )
    admin_session.add(er)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "exemption_request"
    assert ev.date == "2026-06-15"
    assert et.name in ev.title
    assert ev.description == "נפצעתי"


def test_personal_constraint_appears(admin_session, soldier):
    """A PersonalConstraint produces a 'personal_constraint' event."""
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 21),
        reason="אירוע משפחתי",
    )
    admin_session.add(c)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "personal_constraint"
    assert ev.date == "2026-06-20"
    assert ev.title == "אילוצים אישיים"
    assert ev.description == "אירוע משפחתי"


def test_sorted_descending(admin_session, soldier, duty_type, location):
    """Events are sorted newest date first."""
    a_early = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        status="published",
    )
    a_late = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        status="published",
    )
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 2),
        reason="test",
    )
    admin_session.add_all([a_early, a_late, c])
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)

    dates = [ev.date for ev in events]
    assert dates == sorted(dates, reverse=True), f"Expected descending order, got: {dates}"
