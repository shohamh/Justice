from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType, Soldier
from app.services import scoring as svc
from app.services.settings_loader import set_setting


def _seed(session):
    dt = DutyType(name="שמירה-score", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-score")
    s_primary = Soldier(personal_number="sp01", full_name="Primary", password_hash="x",
                        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    s_reserve = Soldier(personal_number="sr01", full_name="Reserve", password_hash="x",
                        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, s_primary, s_reserve])
    session.flush()
    return dt, loc, s_primary, s_reserve


def test_standby_reserve_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None)
    assign = DutyAssignment(
        soldier_id=s_reserve.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3),
        status="published", is_reserve=True,
    )
    admin_session.add(assign); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    assert scores.get(s_reserve.id, Decimal("0")) == Decimal("0.4")


def test_called_up_reserve_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None)
    set_setting(admin_session, "scoring.reserve_called_up_multiplier", Decimal("1.3"), actor_id=None)
    assign = DutyAssignment(
        soldier_id=s_reserve.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3),
        status="published", is_reserve=True,
        called_up_from=date(2026, 6, 1), called_up_to=date(2026, 6, 2),
    )
    admin_session.add(assign); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    assert scores.get(s_reserve.id, Decimal("0")) == Decimal("2.6")


def test_partial_called_up_reserve_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None)
    set_setting(admin_session, "scoring.reserve_called_up_multiplier", Decimal("1.3"), actor_id=None)
    # 3-day reserve; called up only day 2 → 0.2 + 1.3 + 0.2 = 1.7
    assign = DutyAssignment(
        soldier_id=s_reserve.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 4),
        status="published", is_reserve=True,
        called_up_from=date(2026, 6, 2), called_up_to=date(2026, 6, 2),
    )
    admin_session.add(assign); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    assert scores.get(s_reserve.id, Decimal("0")) == Decimal("1.7")


def test_dismissed_primary_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.dismissed_multiplier", Decimal("0.0"), actor_id=None)
    assign = DutyAssignment(
        soldier_id=s_primary.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 4),
        status="published", is_reserve=False,
    )
    admin_session.add(assign); admin_session.flush()
    dismissal = DutyDismissal(
        duty_assignment_id=assign.id,
        dismissed_from=date(2026, 6, 2), dismissed_to=date(2026, 6, 3),
    )
    admin_session.add(dismissal); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    # day 1 normal (1.0), days 2-3 dismissed (0.0) = 1.0
    assert scores.get(s_primary.id, Decimal("0")) == Decimal("1.0")


def test_normal_primary_unaffected(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    assign = DutyAssignment(
        soldier_id=s_primary.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3),
        status="published", is_reserve=False,
    )
    admin_session.add(assign); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    assert scores.get(s_primary.id, Decimal("0")) == Decimal("2.0")
