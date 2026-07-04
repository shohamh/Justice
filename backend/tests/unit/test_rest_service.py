from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType
from app.services.rest import (
    earliest_eligible_date,
    effective_assignment_end,
    resolve_rest_hours,
)
from tests.helpers import create_soldier


def _make_assignment(session, *, start, end, start_time="08:00", end_time="17:00"):
    dt = DutyType(name=f"dt-{start.isoformat()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc-{start.isoformat()}")
    session.add_all([dt, loc])
    session.flush()
    s = create_soldier(session, personal_number=f"81{start.day:05d}")
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=end, start_time=start_time, end_time=end_time,
        status="published",
    )
    session.add(a)
    session.flush()
    return a, dt


def test_resolve_rest_hours_uses_type_override():
    dt = DutyType(name="dt-override", score_per_day=Decimal("1.00"), requirements={"rest_hours": 8})
    assert resolve_rest_hours(dt, default_rest_hours=12) == 8


def test_resolve_rest_hours_falls_back_to_default():
    dt = DutyType(name="dt-no-override", score_per_day=Decimal("1.00"))
    assert resolve_rest_hours(dt, default_rest_hours=12) == 12


def test_effective_end_normal_assignment(admin_session):
    a, _ = _make_assignment(admin_session, start=date(2026, 6, 1), end=date(2026, 6, 4))
    admin_session.flush()
    end_dt = effective_assignment_end(admin_session, a)
    # last_duty_day(06-01, 06-04) == 06-03, at end_time 17:00
    assert end_dt.isoformat() == "2026-06-03T17:00:00"


def test_effective_end_uses_dismissal_when_soldier_never_returns(admin_session):
    a, _ = _make_assignment(admin_session, start=date(2026, 6, 1), end=date(2026, 6, 5))
    admin_session.flush()
    # Dismissed from 06-03 through 06-04 (the last duty day) — never returns.
    dismissal = DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 6, 3), dismissed_to=date(2026, 6, 4),
    )
    admin_session.add(dismissal)
    admin_session.flush()
    end_dt = effective_assignment_end(admin_session, a)
    # dismissed_from (06-03) combined with the assignment's start_time (08:00)
    assert end_dt.isoformat() == "2026-06-03T08:00:00"


def test_effective_end_ignores_temporary_dismissal_with_return(admin_session):
    a, _ = _make_assignment(admin_session, start=date(2026, 6, 1), end=date(2026, 6, 10))
    admin_session.flush()
    # Dismissed 06-03..06-05, but the assignment runs through 06-09 (last day) —
    # the soldier returns, so this must NOT shorten the effective end.
    dismissal = DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 6, 3), dismissed_to=date(2026, 6, 5),
    )
    admin_session.add(dismissal)
    admin_session.flush()
    end_dt = effective_assignment_end(admin_session, a)
    assert end_dt.isoformat() == "2026-06-09T17:00:00"


def test_earliest_eligible_date_rounds_up_partial_day():
    from datetime import datetime
    effective_end = datetime(2026, 6, 1, 17, 0)
    # +12h = 2026-06-02 05:00 — not midnight, rounds up to 06-03.
    assert earliest_eligible_date(effective_end, rest_hours=12) == date(2026, 6, 3)


def test_earliest_eligible_date_exact_midnight_no_roundup():
    from datetime import datetime
    effective_end = datetime(2026, 6, 1, 12, 0)
    # +12h = 2026-06-02 00:00 exactly — no roundup needed.
    assert earliest_eligible_date(effective_end, rest_hours=12) == date(2026, 6, 2)


def test_earliest_eligible_date_stacks_extra_days():
    from datetime import datetime
    effective_end = datetime(2026, 6, 1, 12, 0)
    assert earliest_eligible_date(effective_end, rest_hours=12, extra_days=7) == date(2026, 6, 9)
