from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    Soldier,
    SystemSetting,
)
from app.services import reserves as svc
from app.services.reserves import ReserveError, check_reserve_cap, relink_reserve


def _seed(session):
    dt = DutyType(name="שמירה-res", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-res")
    s = Soldier(
        personal_number="srv01",
        full_name="A",
        password_hash="x",
        role="soldier",
        enrolled_at=date(2026, 1, 1),
        must_change_password=False,
    )
    r = Soldier(
        personal_number="srv02",
        full_name="B",
        password_hash="x",
        role="soldier",
        enrolled_at=date(2026, 1, 1),
        must_change_password=False,
    )
    session.add_all([dt, loc, s, r])
    session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 8),
        required_count=1,
    )
    session.add(shift)
    session.flush()
    primary = DutyAssignment(
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 8),
        status="published",
        is_reserve=False,
        duty_shift_id=shift.id,
    )
    reserve = DutyAssignment(
        soldier_id=r.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 8),
        status="published",
        is_reserve=True,
        duty_shift_id=shift.id,
    )
    session.add_all([primary, reserve])
    session.flush()
    return shift, primary, reserve, s, r


def test_call_up_reserve_sets_range(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    svc.call_up_reserve(
        admin_session,
        assignment=reserve,
        from_date=date(2026, 6, 3),
        to_date=date(2026, 6, 7),
        actor_id=None,
    )
    assert reserve.called_up_from == date(2026, 6, 3)
    assert reserve.called_up_to == date(2026, 6, 7)


def test_call_up_reserve_rejects_non_reserve(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.call_up_reserve(
            admin_session,
            assignment=primary,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 3),
            actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "not_a_reserve"


def test_call_up_reserve_rejects_out_of_range(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.call_up_reserve(
            admin_session,
            assignment=reserve,
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 5),
            actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "date_out_of_range"


def test_dismiss_primary_creates_record(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    dismissal = svc.dismiss_primary(
        admin_session,
        assignment=primary,
        from_date=date(2026, 6, 5),
        to_date=date(2026, 6, 7),
        reason="חופש",
        actor_id=None,
    )
    assert dismissal.dismissed_from == date(2026, 6, 5)
    assert dismissal.dismissed_to == date(2026, 6, 7)
    assert dismissal.reason == "חופש"


def test_dismiss_primary_rejects_reserve(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.dismiss_primary(
            admin_session,
            assignment=reserve,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 2),
            reason=None,
            actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "not_a_primary"


def test_dismiss_primary_rejects_overlapping_dismissal(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    svc.dismiss_primary(
        admin_session,
        assignment=primary,
        from_date=date(2026, 6, 3),
        to_date=date(2026, 6, 5),
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    try:
        svc.dismiss_primary(
            admin_session,
            assignment=primary,
            from_date=date(2026, 6, 4),
            to_date=date(2026, 6, 6),
            reason=None,
            actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "overlapping_dismissal"


def test_delete_dismissal(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    dismissal = svc.dismiss_primary(
        admin_session,
        assignment=primary,
        from_date=date(2026, 6, 5),
        to_date=date(2026, 6, 7),
        reason=None,
        actor_id=None,
    )
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


def test_relink_reserve(admin_session):
    from tests.helpers import create_soldier, create_node
    from datetime import date
    from decimal import Decimal
    from app.db.models import DutyType, DutyLocation

    parent = create_node(admin_session, level="division", name="relink-parent")
    child = create_node(admin_session, level="unit", name="relink-child", parent=parent)

    dt = DutyType(name="relink-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="relink-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    p_soldier = create_soldier(admin_session, personal_number="800001", hierarchy_node_id=parent.id)
    r_soldier = create_soldier(admin_session, personal_number="800002", hierarchy_node_id=child.id)
    admin_session.flush()

    primary = DutyAssignment(
        soldier_id=p_soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
    )
    reserve_a = DutyAssignment(
        soldier_id=r_soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        is_reserve=True,
    )
    admin_session.add_all([primary, reserve_a])
    admin_session.flush()

    link = DutyReserveLink(
        primary_assignment_id=primary.id, reserve_assignment_id=reserve_a.id, hierarchy_distance=1
    )
    admin_session.add(link)
    admin_session.flush()

    result = relink_reserve(
        admin_session, primary_assignment=primary, reserve_assignment_id=reserve_a.id, actor_id=None
    )
    assert result.hierarchy_distance == 1

    links = (
        admin_session.execute(
            select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == primary.id)
        )
        .scalars()
        .all()
    )
    assert len(links) == 1


def test_relink_reserve_non_reserve_fails(admin_session):
    from tests.helpers import create_soldier
    from datetime import date
    from decimal import Decimal
    from app.db.models import DutyType, DutyLocation

    dt = DutyType(name="fail-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="fail-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    p_soldier = create_soldier(admin_session, personal_number="800003")
    r_soldier = create_soldier(admin_session, personal_number="800004")
    admin_session.flush()

    primary = DutyAssignment(
        soldier_id=p_soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
    )
    not_reserve = DutyAssignment(
        soldier_id=r_soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        is_reserve=False,
    )
    admin_session.add_all([primary, not_reserve])
    admin_session.flush()

    import pytest

    with pytest.raises(ReserveError, match="not_a_reserve"):
        relink_reserve(
            admin_session,
            primary_assignment=primary,
            reserve_assignment_id=not_reserve.id,
            actor_id=None,
        )


# --- Cap utility tests ---


def _make_soldier(session, pn="cap01"):
    dt = DutyType(name=f"שמירה-{pn}", score_per_day=Decimal("1"))
    loc = DutyLocation(name=f"עמדה-{pn}")
    s = Soldier(
        personal_number=pn, full_name=pn, password_hash="x",
        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False,
    )
    session.add_all([dt, loc, s])
    session.flush()
    return s, dt, loc


def _reserve(session, soldier_id, dt_id, loc_id, start, end, status="published"):
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt_id, duty_location_id=loc_id,
        start_date=start, end_date=end, status=status, is_reserve=True,
    )
    session.add(a)
    session.flush()
    return a


def test_cap_passes_when_no_existing_reserves(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-none")
    passes, current, max_days = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 1), date(2026, 7, 8)
    )
    assert passes is True
    assert current == 7   # candidate days only
    assert max_days == 14


def test_cap_passes_exactly_at_limit(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-exact")
    # 7 existing reserve days, candidate adds 7 more = 14 total, which equals the cap
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 8))
    passes, current, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 8), date(2026, 7, 15)
    )
    assert passes is True
    assert current == 14


def test_cap_fails_one_over_limit(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-over")
    # 8 existing days in same 30-day window, candidate adds 7 more = 15 > 14
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 9))
    passes, current, max_days = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 9), date(2026, 7, 16)
    )
    assert passes is False
    assert current == 15
    assert max_days == 14


def test_cap_respects_settings_override(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-setting")
    admin_session.add(SystemSetting(key="reserves.max_days_per_window", value=7))
    admin_session.flush()
    # 4 existing + 4 candidate = 8 > 7
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 5))
    passes, current, max_days = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 5), date(2026, 7, 9)
    )
    assert passes is False
    assert max_days == 7


def test_cap_ignores_primary_assignments(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-primary")
    # 14 PRIMARY days should not count toward the reserve cap
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 15),
        status="published", is_reserve=False,
    )
    admin_session.add(a)
    admin_session.flush()
    passes, current, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 1), date(2026, 7, 8)
    )
    assert passes is True
    assert current == 7


def test_cap_counts_algorithm_draft_reserves(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-draft")
    # algorithm_draft reserves should also count
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 9), status="algorithm_draft")
    passes, _, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 9), date(2026, 7, 16)
    )
    assert passes is False


def test_cap_respects_window_days_override(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-wdays")
    # Default window is 30 days. Override to 10 days.
    # Two ranges 12 days apart won't collide in a 10-day window but would in a 30-day one.
    admin_session.add(SystemSetting(key="reserves.window_days", value=10))
    admin_session.flush()
    # 5 existing days (Jul 1-5), candidate Jul 17-21 (5 days) — 12 days apart, no 10-day window spans both
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 6))
    passes, current, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 17), date(2026, 7, 22)
    )
    assert passes is True   # would exceed 14 in a 30-day window but not in a 10-day window
    assert current == 5     # peak is 5 (only one side fits per 10-day window)
