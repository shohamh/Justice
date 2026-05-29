from datetime import date

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType, ExemptionType, SoldierExemption
from app.services.assignments import AssignmentError, cancel_assignment, create_assignment
from app.services.duty_config import map_exemption_to_duty_type
from tests.helpers import create_soldier


def _dt(session, name="dt", score="1.00"):
    from decimal import Decimal
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _loc(session, name="loc"):
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_create_assignment(admin_session):
    s = create_soldier(admin_session, personal_number="8100001")
    dt = _dt(admin_session, "שמירה-a1")
    loc = _loc(admin_session, "מוצב-a1")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), notes="ok", actor_id=None)
    admin_session.commit()
    assert a.status == "published"
    assert a.start_date == date(2026, 6, 1)


def test_create_rejects_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="8100002")
    dt = _dt(admin_session, "שמירה-a2")
    loc = _loc(admin_session, "מוצב-a2")
    with pytest.raises(AssignmentError):
        create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 5), end_date=date(2026, 6, 1), notes=None, actor_id=None)


def test_create_rejects_overlap(admin_session):
    s = create_soldier(admin_session, personal_number="8100003")
    dt = _dt(admin_session, "שמירה-a3")
    loc = _loc(admin_session, "מוצב-a3")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 5), notes=None, actor_id=None)
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 4), end_date=date(2026, 6, 7), notes=None, actor_id=None)
    assert "overlap" in str(exc.value)


def test_create_rejects_exempted_soldier(admin_session):
    s = create_soldier(admin_session, personal_number="8100004")
    dt = _dt(admin_session, "שמירה-a4")
    loc = _loc(admin_session, "מוצב-a4")
    et = ExemptionType(name="פטור-a4")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    admin_session.add(SoldierExemption(soldier_id=s.id, exemption_type_id=et.id,
                                       start_date=date(2026, 6, 1), end_date=None))
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 2), end_date=date(2026, 6, 4), notes=None, actor_id=None)
    assert "exempted" in str(exc.value)


def test_cancel_assignment(admin_session):
    s = create_soldier(admin_session, personal_number="8100005")
    dt = _dt(admin_session, "שמירה-a5")
    loc = _loc(admin_session, "מוצב-a5")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None)
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.commit()
    assert a.status == "cancelled"
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None)
    admin_session.commit()


def test_cancel_requires_reason(admin_session):
    s = create_soldier(admin_session, personal_number="8100006")
    dt = _dt(admin_session, "שמירה-a6")
    loc = _loc(admin_session, "מוצב-a6")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None)
    admin_session.flush()
    with pytest.raises(AssignmentError):
        cancel_assignment(admin_session, assignment=a, reason="  ", actor_id=None)
