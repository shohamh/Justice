from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from app.services.adjustments import create_adjustment
from app.services.assignments import cancel_assignment, create_assignment, set_day_override
from app.services.scoring import cumulative_score, effective_duty_days
from tests.helpers import create_soldier


def _dt(session, name, score):
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _loc(session, name):
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_effective_days_basic_block(admin_session):
    s = create_soldier(admin_session, personal_number="8400001")
    dt = _dt(admin_session, "שמירה-sc1", "1.00")
    loc = _loc(admin_session, "מוצב-sc1")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), notes=None, actor_id=None)
    admin_session.flush()
    days = [d for d in effective_duty_days(admin_session) if d[1] == s.id]
    assert len(days) == 3


def test_cumulative_with_override_and_adjustment(admin_session):
    s = create_soldier(admin_session, personal_number="8400002")
    repl = create_soldier(admin_session, personal_number="8400003")
    dt = _dt(admin_session, "שמירה-sc2", "2.00")
    loc = _loc(admin_session, "מוצב-sc2")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), notes=None, actor_id=None)
    admin_session.flush()
    set_day_override(admin_session, assignment=a, date=date(2026, 9, 2),
                     effective_soldier_id=repl.id, reason="replacement", actor_id=None)
    set_day_override(admin_session, assignment=a, date=date(2026, 9, 3),
                     effective_soldier_id=None, reason="cancelled", actor_id=None)
    create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("5.00"), reason="פיצוי", actor_id=None)
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("7.00")
    assert cumulative_score(admin_session, soldier_id=repl.id) == Decimal("2.00")


def test_cancelled_assignment_excluded(admin_session):
    s = create_soldier(admin_session, personal_number="8400004")
    dt = _dt(admin_session, "שמירה-sc3", "3.00")
    loc = _loc(admin_session, "מוצב-sc3")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), notes=None, actor_id=None)
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("0")
