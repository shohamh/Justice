from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import DutyLocation, DutyType, ExemptionType, SoldierExemption
from app.services.adjustments import create_adjustment
from app.services.assignments import cancel_assignment, create_assignment, set_day_override
from app.services.duty_config import map_exemption_to_duty_type
from app.services.scoring import (
    active_days,
    cumulative_score,
    effective_duty_days,
    normalised_score,
    soldier_score_breakdown,
    transparency_rows,
)
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
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    days = [d for d in effective_duty_days(admin_session) if d[1] == s.id]
    assert len(days) == 3


def test_cumulative_with_override_and_adjustment(admin_session):
    s = create_soldier(admin_session, personal_number="8400002")
    repl = create_soldier(admin_session, personal_number="8400003")
    dt = _dt(admin_session, "שמירה-sc2", "2.00")
    loc = _loc(admin_session, "מוצב-sc2")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 9, 2),
        effective_soldier_id=repl.id,
        reason="replacement",
        actor_id=None,
    )
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 9, 3),
        effective_soldier_id=None,
        reason="cancelled",
        actor_id=None,
    )
    create_adjustment(
        admin_session, soldier_id=s.id, delta=Decimal("5.00"), reason="פיצוי", actor_id=None
    )
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("7.00")
    assert cumulative_score(admin_session, soldier_id=repl.id) == Decimal("2.00")


def test_cancelled_assignment_excluded(admin_session):
    s = create_soldier(admin_session, personal_number="8400004")
    dt = _dt(admin_session, "שמירה-sc3", "3.00")
    loc = _loc(admin_session, "מוצב-sc3")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("0")


def test_active_days_subtracts_full_coverage_exemption(admin_session):
    s = create_soldier(admin_session, personal_number="8500001")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    _dt(admin_session, "שמירה-ad1", "1.00")
    et = ExemptionType(name="פטור-מלא-ad1")
    admin_session.add(et)
    admin_session.flush()
    # Full coverage = exemption maps to EVERY currently-active duty type. Other tests in the
    # shared session commit duty types too, so map to all active ones (not just this test's).
    active_ids = (
        admin_session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )
    for dtid in active_ids:
        map_exemption_to_duty_type(
            admin_session, exemption_type_id=et.id, duty_type_id=dtid, actor_id=None
        )
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date.today() - timedelta(days=4),
            end_date=date.today(),
        )
    )
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 5


def test_active_days_floor_is_one(admin_session):
    s = create_soldier(admin_session, personal_number="8500002")
    s.enrolled_at = date.today()
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 1


def test_partial_coverage_does_not_reduce_active_days(admin_session):
    s = create_soldier(admin_session, personal_number="8500003")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    d1 = _dt(admin_session, "שמירה-ad3a", "1.00")
    _dt(admin_session, "ניקיון-ad3b", "1.00")
    et = ExemptionType(name="פטור-חלקי-ad3")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(
        admin_session, exemption_type_id=et.id, duty_type_id=d1.id, actor_id=None
    )
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date.today() - timedelta(days=4),
            end_date=date.today(),
        )
    )
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 10


def test_normalised_and_transparency(admin_session):
    s = create_soldier(admin_session, personal_number="8500004")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    dt = _dt(admin_session, "שמירה-tr", "2.00")
    loc = _loc(admin_session, "מוצב-tr")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=3),
        end_date=date.today() - timedelta(days=2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    assert normalised_score(admin_session, soldier=s) == Decimal("4.00") / Decimal("10")
    rows = transparency_rows(admin_session)
    mine = next(r for r in rows if r["soldier_id"] == s.id)
    assert mine["cumulative_score"] == Decimal("4.00")
    assert mine["active_days"] == 10
    norms = [r["normalised_score"] for r in rows]
    assert norms == sorted(norms, reverse=True)


def test_breakdown(admin_session):
    s = create_soldier(admin_session, personal_number="8500005")
    dt = _dt(admin_session, "שמירה-bd", "1.50")
    loc = _loc(admin_session, "מוצב-bd")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        notes=None,
        actor_id=None,
    )
    create_adjustment(
        admin_session, soldier_id=s.id, delta=Decimal("3.00"), reason="פיצוי", actor_id=None
    )
    admin_session.flush()
    bd = soldier_score_breakdown(admin_session, soldier_id=s.id)
    assert any(pt["days"] == 2 and pt["score"] == Decimal("3.00") for pt in bd["per_type"])
    assert len(bd["adjustments"]) == 1
