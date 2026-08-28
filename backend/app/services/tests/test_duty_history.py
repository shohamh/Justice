"""Tests for app.services.duty_history.get_duty_history."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    AuditLog,
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
    PersonalConstraintOverride,
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


def test_personal_constraint_reason_hidden_when_not_sensitive(admin_session, soldier):
    """A viewer without private-info visibility must not see the constraint's
    reason via duty history, even though the event itself (dates, status)
    stays visible. Regression test: get_duty_history previously ignored
    include_sensitive for personal_constraint events."""
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 21),
        reason="אירוע משפחתי",
    )
    admin_session.add(c)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id, include_sensitive=False)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "personal_constraint"
    assert ev.title == "אילוצים אישיים"
    assert ev.description is None


def test_constraint_override_appears(admin_session, soldier):
    """A PersonalConstraintOverride produces a 'personal_constraint_override' event."""
    overrider = create_soldier(admin_session, personal_number=f"99{_uid()}", role="commander")
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 21),
        reason="אירוע משפחתי",
        status="approved",
    )
    admin_session.add(c)
    admin_session.flush()
    o = PersonalConstraintOverride(
        personal_constraint_id=c.id,
        soldier_id=soldier.id,
        overridden_by=overrider.id,
        assignment_kind="range",
        reference_id=c.id,
        reason="צורך מבצעי",
    )
    admin_session.add(o)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id, include_sensitive=True)
    override_events = [e for e in events if e.event_type == "personal_constraint_override"]

    assert len(override_events) == 1
    ev = override_events[0]
    assert ev.description == "צורך מבצעי"
    assert ev.metadata["overridden_by_name"] == overrider.full_name


def test_constraint_override_reason_hidden_when_not_sensitive(admin_session, soldier):
    """A viewer without private-info visibility must not see the override's
    reason or overrider name via duty history."""
    overrider = create_soldier(admin_session, personal_number=f"99{_uid()}", role="commander")
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 6, 20),
        end_date=date(2026, 6, 21),
        reason="אירוע משפחתי",
        status="approved",
    )
    admin_session.add(c)
    admin_session.flush()
    o = PersonalConstraintOverride(
        personal_constraint_id=c.id,
        soldier_id=soldier.id,
        overridden_by=overrider.id,
        assignment_kind="duty",
        reference_id=c.id,
        reason="צורך מבצעי",
    )
    admin_session.add(o)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id, include_sensitive=False)
    override_events = [e for e in events if e.event_type == "personal_constraint_override"]

    assert len(override_events) == 1
    ev = override_events[0]
    assert ev.description is None
    assert ev.metadata == {}


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


# ---------------------------------------------------------------------------
# Score metadata tests
# ---------------------------------------------------------------------------


def test_assignment_score_regular(admin_session, soldier, duty_type, location):
    """Regular 3-day assignment: score_total='3.0', formula='3 × 1.0 × 1.0'."""
    # duty_type has score_per_day=Decimal("1.00")
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 13),  # 3 days: [2026-06-10, 2026-06-13) exclusive
        status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "assignment")

    assert ev.metadata["score_total"] == "3.0"
    assert ev.metadata["score_formula"] == "3 × 1.0 × 1.0"


def test_assignment_score_reserve_standby_only(admin_session, soldier, duty_type, location):
    """Reserve 3-day standby (no call-up): score=0.6, formula uses standby multiplier 0.2."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 13),  # 3 days inclusive (exclusive end boundary)
        status="published",
        is_reserve=True,
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "assignment")

    assert ev.metadata["score_total"] == "0.6"
    assert ev.metadata["score_formula"] == "3 × 1.0 × 0.2"


def test_assignment_score_reserve_with_calledup(admin_session, soldier, duty_type, location):
    """Reserve 5-day assignment where days 3-4 are called up.

    Days 1-2 (Jun 10-11): standby ×0.2  → 0.4
    Days 3-4 (Jun 12-13): called-up ×1.3 → 2.6
    Day 5   (Jun 14):     standby ×0.2  → 0.2
    Total: 3.2
    """
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),  # 5 days inclusive (exclusive end boundary)
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 6, 12),
        called_up_to=date(2026, 6, 13),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "assignment")

    assert ev.metadata["score_total"] == "3.2"
    assert ev.metadata["score_formula"] == "2 × 1.0 × 0.2 + 2 × 1.0 × 1.3 + 1 × 1.0 × 0.2"


def test_call_up_score_within_assignment(admin_session, soldier, duty_type, location):
    """call_up event carries score for the called-up sub-period only."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 6, 12),
        called_up_to=date(2026, 6, 13),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    call_up_ev = next(e for e in events if e.event_type == "call_up")

    assert call_up_ev.metadata["score_total"] == "2.6"
    assert call_up_ev.metadata["score_formula"] == "2 × 1.0 × 1.3"


def test_call_up_score_zero_when_outside_assignment(admin_session, soldier, duty_type, location):
    """call_up event before the main assignment span scores 0 (no overlap)."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 6, 8),   # before start_date — no overlap
        called_up_to=date(2026, 6, 9),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    call_up_ev = next(e for e in events if e.event_type == "call_up")

    assert call_up_ev.metadata["score_total"] == "0.0"
    assert call_up_ev.metadata.get("score_formula", "") == ""


def test_dismissal_score_is_zero(admin_session, soldier, duty_type, location):
    """Dismissal event carries score=0 with formula showing dismissed multiplier."""
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
    dismissal_ev = next(e for e in events if e.event_type == "dismissal")

    assert dismissal_ev.metadata["score_total"] == "0.0"
    assert dismissal_ev.metadata["score_formula"] == "2 × 1.0 × 0.0"


def test_cancellation_score_is_zero(admin_session, soldier, duty_type, location):
    """Cancelled assignment carries score_total='0' and no formula."""
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
    ev = next(e for e in events if e.event_type == "cancellation")

    assert ev.metadata["score_total"] == "0.0"
    assert "score_formula" not in ev.metadata


def test_draft_hidden_by_default(admin_session, soldier, duty_type, location):
    """algorithm_draft assignment does NOT appear when include_drafts is False."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="algorithm_draft",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    assert events == []


def test_draft_shown_with_include_drafts(admin_session, soldier, duty_type, location):
    """algorithm_draft assignment appears when include_drafts=True."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="algorithm_draft",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id, include_drafts=True)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "assignment"
    assert ev.status == "algorithm_draft"


def test_duty_history_annotates_revoked_exemption(admin_session):
    """A revoked SoldierExemption's event metadata includes revocation details."""
    from datetime import datetime, timezone

    from app.db.models import SoldierExemption

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    revoker = create_soldier(admin_session, personal_number=f"99{_uid()}")
    revoker.full_name = "מבטל בדיקה"
    et = ExemptionType(name=f"dh-revoke-test_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date.today(), end_date=date.today(),
        revoked_at=datetime.now(timezone.utc), revoked_by=revoker.id,
        revoke_reason="כבר לא נדרש",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id)
    exemption_events = [e for e in events if e.event_type == "exemption"]
    assert len(exemption_events) == 1
    meta = exemption_events[0].metadata
    assert meta["revoke_reason"] == "כבר לא נדרש"
    assert meta["revoked_by_name"] == "מבטל בדיקה"
    assert meta["revoked_at"] is not None


def test_duty_history_no_revocation_metadata_when_not_revoked(admin_session):
    """A non-revoked SoldierExemption's event metadata has no revocation keys."""
    from app.db.models import SoldierExemption

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    et = ExemptionType(name=f"dh-norevoke-test_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date.today(), end_date=None,
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id)
    exemption_events = [e for e in events if e.event_type == "exemption"]
    assert len(exemption_events) == 1
    assert exemption_events[0].metadata.get("revoke_reason") is None


def test_duty_history_hides_revocation_metadata_when_include_sensitive_false(admin_session):
    """Out-of-scope viewers (include_sensitive=False) must not see revoke_reason/
    revoked_by_name/revoked_at — mirroring exemptions.py's can_see_private gate."""
    from datetime import datetime, timezone

    from app.db.models import SoldierExemption

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    revoker = create_soldier(admin_session, personal_number=f"99{_uid()}")
    revoker.full_name = "מבטל בדיקה"
    et = ExemptionType(name=f"dh-revoke-hidden-test_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date.today(), end_date=date.today(),
        revoked_at=datetime.now(timezone.utc), revoked_by=revoker.id,
        revoke_reason="כבר לא נדרש",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id, include_sensitive=False)
    exemption_events = [e for e in events if e.event_type == "exemption"]
    assert len(exemption_events) == 1
    meta = exemption_events[0].metadata
    assert "revoke_reason" not in meta
    assert "revoked_by_name" not in meta
    assert "revoked_at" not in meta


def test_duty_history_annotates_cancelled_constraint(admin_session):
    """A cancelled PersonalConstraint's event metadata includes cancellation details."""
    from datetime import datetime, timezone

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller.full_name = "מבטל בדיקה"
    admin_session.add(PersonalConstraint(
        soldier_id=s.id, start_date=date(2026, 6, 20), end_date=date(2026, 6, 21),
        reason="אירוע משפחתי", status="cancelled",
        decided_by=canceller.id, decided_at=datetime.now(timezone.utc),
        decision_note="כבר לא נדרש",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id)
    constraint_events = [e for e in events if e.event_type == "personal_constraint"]
    assert len(constraint_events) == 1
    meta = constraint_events[0].metadata
    assert meta["cancelled_by_name"] == "מבטל בדיקה"
    assert meta["cancelled_at"] is not None
    assert meta["decision_note"] == "כבר לא נדרש"


def test_duty_history_no_cancellation_metadata_when_not_cancelled(admin_session, soldier):
    """A pending/approved PersonalConstraint's event metadata has no cancellation keys."""
    admin_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=date(2026, 6, 20), end_date=date(2026, 6, 21),
        reason="אירוע משפחתי", status="approved",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, soldier.id)
    constraint_events = [e for e in events if e.event_type == "personal_constraint"]
    assert len(constraint_events) == 1
    assert "cancelled_by_name" not in constraint_events[0].metadata
    assert "cancelled_at" not in constraint_events[0].metadata


def test_duty_history_hides_cancellation_metadata_when_include_sensitive_false(admin_session):
    """Out-of-scope viewers (include_sensitive=False) must not see cancellation
    attribution — mirroring exemptions.py's can_see_private gate."""
    from datetime import datetime, timezone

    s = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller = create_soldier(admin_session, personal_number=f"99{_uid()}")
    canceller.full_name = "מבטל בדיקה"
    admin_session.add(PersonalConstraint(
        soldier_id=s.id, start_date=date(2026, 6, 20), end_date=date(2026, 6, 21),
        reason="אירוע משפחתי", status="cancelled",
        decided_by=canceller.id, decided_at=datetime.now(timezone.utc),
        decision_note="כבר לא נדרש",
    ))
    admin_session.commit()

    events = get_duty_history(admin_session, s.id, include_sensitive=False)
    constraint_events = [e for e in events if e.event_type == "personal_constraint"]
    assert len(constraint_events) == 1
    meta = constraint_events[0].metadata
    assert "cancelled_by_name" not in meta
    assert "cancelled_at" not in meta
    assert "decision_note" not in meta or meta["decision_note"] is None


def test_swap_override_appears_in_receiving_soldiers_history(admin_session, duty_type, location):
    """A day received via swap (DutyDayOverride) appears in the receiving soldier's
    history as an 'assignment' event, even though DutyAssignment.soldier_id still
    belongs to the original requester (swaps never mutate soldier_id — only
    DutyDayOverride rows are written)."""
    from app.services.assignments import set_day_override

    original = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    receiver = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    a = DutyAssignment(
        soldier_id=original.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), status="published", is_reserve=False,
    )
    admin_session.add(a)
    admin_session.flush()
    set_day_override(
        admin_session, assignment=a, date=date(2026, 6, 1),
        effective_soldier_id=receiver.id, reason="replacement", actor_id=None,
    )
    admin_session.commit()

    events = get_duty_history(admin_session, receiver.id)

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "assignment"
    assert ev.date == "2026-06-01"
    # end_date follows the exclusive convention used elsewhere in this module
    # (matches DutyAssignment's own end_date semantics) — a single overridden
    # day (2026-06-01) has an exclusive end_date of 2026-06-02.
    assert ev.end_date == "2026-06-02"
    assert ev.metadata["duty_assignment_id"] == str(a.id)
    assert ev.metadata["override_reason"] == "replacement"
    assert duty_type.name in ev.title
    assert location.name in ev.title

    # The original requester still sees the (unmodified) full assignment as
    # their own — this test only asserts the receiver now also sees it.
    original_events = get_duty_history(admin_session, original.id)
    assert len(original_events) == 1
    assert original_events[0].event_type == "assignment"


def test_swap_override_on_draft_assignment_hidden_by_default(admin_session, duty_type, location):
    """An override on a draft assignment must respect the same excluded_statuses
    filter the soldier's own DutyAssignment query applies: it should be hidden
    from the receiving soldier's history when include_drafts=False, and shown
    when include_drafts=True."""
    from app.services.assignments import set_day_override

    original = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    receiver = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    a = DutyAssignment(
        soldier_id=original.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), status="algorithm_draft", is_reserve=False,
    )
    admin_session.add(a)
    admin_session.flush()
    set_day_override(
        admin_session, assignment=a, date=date(2026, 6, 1),
        effective_soldier_id=receiver.id, reason="replacement", actor_id=None,
    )
    admin_session.commit()

    hidden_events = get_duty_history(admin_session, receiver.id, include_drafts=False)
    assert hidden_events == []

    shown_events = get_duty_history(admin_session, receiver.id, include_drafts=True)
    assert len(shown_events) == 1
    assert shown_events[0].event_type == "assignment"
    assert shown_events[0].metadata["duty_assignment_id"] == str(a.id)


def test_swap_override_on_rejected_assignment_always_hidden(admin_session, duty_type, location):
    """An override on an algorithm_rejected assignment must never appear in the
    receiving soldier's history, regardless of include_drafts."""
    from app.services.assignments import set_day_override

    original = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    receiver = create_soldier(admin_session, personal_number=f"99{_uid()}", role="soldier")
    a = DutyAssignment(
        soldier_id=original.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), status="algorithm_rejected", is_reserve=False,
    )
    admin_session.add(a)
    admin_session.flush()
    set_day_override(
        admin_session, assignment=a, date=date(2026, 6, 1),
        effective_soldier_id=receiver.id, reason="replacement", actor_id=None,
    )
    admin_session.commit()

    assert get_duty_history(admin_session, receiver.id, include_drafts=False) == []
    assert get_duty_history(admin_session, receiver.id, include_drafts=True) == []


def test_draft_metadata_includes_job_id(admin_session, soldier, duty_type, location):
    """Draft assignment metadata includes job_id when an audit log entry exists."""
    import uuid as _uuid

    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="algorithm_draft",
    )
    admin_session.add(a)
    admin_session.flush()

    fake_job_id = str(_uuid.uuid4())
    audit = AuditLog(
        action="algorithm.proposal.create",
        entity_type="duty_assignment",
        entity_id=a.id,
        context={"job_id": fake_job_id},
    )
    admin_session.add(audit)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id, include_drafts=True)
    ev = events[0]
    assert ev.metadata["job_id"] == fake_job_id


def test_range_assignment_appears(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_node, create_range_location

    node = create_node(admin_session, level="branch", name="dh-range-node-1")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    weapon_duty = DutyType(
        name=f"שמירה עם נשק {_uid()}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)

    events = get_duty_history(admin_session, soldier.id)

    range_events = [e for e in events if e.event_type == "range_assignment"]
    assert len(range_events) == 1
    assert range_events[0].status == "pending"
    assert range_events[0].metadata["is_reserve"] == "false"
    assert range_events[0].metadata["was_promoted_from_reserve"] == "false"


def test_range_assignment_promoted_from_reserve_flagged(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.range_excusal import decide_primary_excusal, request_primary_excusal
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="dh-range-node-2")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    manager = create_soldier(admin_session, personal_number="dh-range-mgr", role="duty_manager", hierarchy_node_id=node.id)
    primary = create_soldier(admin_session, personal_number="dh-range-primary", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name=f"שמירה עם נשק {_uid()}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1, reserve_count=1,
    )
    primary_assignment = add_range_assignment(admin_session, event=event, soldier_id=primary.id, is_reserve=False)
    add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=True)

    request = request_primary_excusal(admin_session, assignment=primary_assignment, reason="בדיקה", requested_by=primary.id)
    decide_primary_excusal(admin_session, request=request, approve=True, decided_by=manager.id)

    events = get_duty_history(admin_session, soldier.id)
    range_events = [e for e in events if e.event_type == "range_assignment"]
    assert len(range_events) == 1
    assert range_events[0].metadata["was_promoted_from_reserve"] == "true"
    assert range_events[0].metadata["is_reserve"] == "false"


def test_range_removed_via_excusal_appears(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.range_excusal import decide_primary_excusal, request_primary_excusal
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="dh-removed-node-1")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    manager = create_soldier(admin_session, personal_number="dh-removed-mgr", role="duty_manager", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name=f"שמירה עם נשק {_uid()}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)
    request = request_primary_excusal(admin_session, assignment=assignment, reason="חופשה", requested_by=soldier.id)
    decide_primary_excusal(admin_session, request=request, approve=True, decided_by=manager.id)

    events = get_duty_history(admin_session, soldier.id)
    removed = [e for e in events if e.event_type == "range_removed"]
    assert len(removed) == 1
    assert removed[0].description == "חופשה"
    assert removed[0].metadata["source"] == "excusal"
    assert removed[0].metadata["range_type"] == "live"


def test_range_removed_via_manual_removal_appears(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event, remove_range_assignment
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="dh-removed-node-2")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    manager = create_soldier(admin_session, personal_number="dh-removed-mgr2", role="duty_manager", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name=f"שמירה עם נשק {_uid()}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.alal,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)
    remove_range_assignment(admin_session, assignment=assignment, reason="שוחרר מהיחידה", actor_id=manager.id)

    events = get_duty_history(admin_session, soldier.id)
    removed = [e for e in events if e.event_type == "range_removed"]
    assert len(removed) == 1
    assert removed[0].description == "שוחרר מהיחידה"
    assert removed[0].metadata["source"] == "manual_removal"
    assert removed[0].metadata["range_type"] == "alal"
