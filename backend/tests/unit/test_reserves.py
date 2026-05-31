from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyShift, DutyType, Soldier
from app.services import reserves as svc


def _seed(session):
    dt = DutyType(name="שמירה-res", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-res")
    s = Soldier(personal_number="srv01", full_name="A", password_hash="x",
                role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    r = Soldier(personal_number="srv02", full_name="B", password_hash="x",
                role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, s, r]); session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
                      required_count=1)
    session.add(shift); session.flush()
    primary = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
        status="published", is_reserve=False, duty_shift_id=shift.id,
    )
    reserve = DutyAssignment(
        soldier_id=r.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
        status="published", is_reserve=True, duty_shift_id=shift.id,
    )
    session.add_all([primary, reserve]); session.flush()
    return shift, primary, reserve, s, r


def test_call_up_reserve_sets_range(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    svc.call_up_reserve(admin_session, assignment=reserve,
                        from_date=date(2026, 6, 3), to_date=date(2026, 6, 7), actor_id=None)
    assert reserve.called_up_from == date(2026, 6, 3)
    assert reserve.called_up_to == date(2026, 6, 7)


def test_call_up_reserve_rejects_non_reserve(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.call_up_reserve(admin_session, assignment=primary,
                            from_date=date(2026, 6, 1), to_date=date(2026, 6, 3), actor_id=None)
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "not_a_reserve"


def test_call_up_reserve_rejects_out_of_range(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.call_up_reserve(admin_session, assignment=reserve,
                            from_date=date(2026, 5, 1), to_date=date(2026, 5, 5), actor_id=None)
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "date_out_of_range"


def test_dismiss_primary_creates_record(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    dismissal = svc.dismiss_primary(admin_session, assignment=primary,
                                    from_date=date(2026, 6, 5), to_date=date(2026, 6, 7),
                                    reason="חופש", actor_id=None)
    assert dismissal.dismissed_from == date(2026, 6, 5)
    assert dismissal.dismissed_to == date(2026, 6, 7)
    assert dismissal.reason == "חופש"


def test_dismiss_primary_rejects_reserve(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.dismiss_primary(admin_session, assignment=reserve,
                            from_date=date(2026, 6, 1), to_date=date(2026, 6, 2),
                            reason=None, actor_id=None)
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "not_a_primary"


def test_dismiss_primary_rejects_overlapping_dismissal(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    svc.dismiss_primary(admin_session, assignment=primary,
                        from_date=date(2026, 6, 3), to_date=date(2026, 6, 5), reason=None, actor_id=None)
    admin_session.flush()
    try:
        svc.dismiss_primary(admin_session, assignment=primary,
                            from_date=date(2026, 6, 4), to_date=date(2026, 6, 6), reason=None, actor_id=None)
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "overlapping_dismissal"


def test_delete_dismissal(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    dismissal = svc.dismiss_primary(admin_session, assignment=primary,
                                    from_date=date(2026, 6, 5), to_date=date(2026, 6, 7),
                                    reason=None, actor_id=None)
    admin_session.flush()
    svc.delete_dismissal(admin_session, dismissal=dismissal, actor_id=None)
    admin_session.flush()
    from sqlalchemy import select
    remaining = admin_session.execute(select(DutyDismissal)).scalars().all()
    assert len(remaining) == 0


def test_get_shift_reserve_detail(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    detail = svc.get_shift_reserve_detail(admin_session, shift_id=shift.id)
    assert len(detail["primaries"]) == 1
    assert len(detail["reserves"]) == 1
    assert detail["primaries"][0]["soldier_id"] == s.id
    assert detail["reserves"][0]["soldier_id"] == r.id
