from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyReserveLink, DutyShift, DutyType
from app.services import gimelim as svc
from tests.helpers import create_soldier


def _seed(session):
    dt = DutyType(name="dt_gimelim_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_gimelim_test")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def test_gimelim_promotion_copies_future_shift_times(admin_session):
    """When A is dismissed via gimelim and rolled onto a future shift (promoting
    A and demoting C), the new primary assignment must copy the future shift's
    start_time/end_time rather than defaulting to 00:00/23:59."""
    session = admin_session
    dt, loc = _seed(session)

    soldier_a = create_soldier(session, personal_number="9100001")
    soldier_b = create_soldier(session, personal_number="9100002")  # reserve for A's current shift
    soldier_c = create_soldier(session, personal_number="9100003")  # primary on future shift

    # A's current shift/assignment
    current_shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 2),
        start_time="08:00", end_time="17:00",
    )
    session.add(current_shift)
    session.flush()

    primary_a = DutyAssignment(
        soldier_id=soldier_a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=current_shift.start_date, end_date=current_shift.end_date,
        duty_shift_id=current_shift.id, is_reserve=False, status="published",
    )
    session.add(primary_a)
    session.flush()

    reserve_b = DutyAssignment(
        soldier_id=soldier_b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=current_shift.start_date, end_date=current_shift.end_date,
        duty_shift_id=current_shift.id, is_reserve=True, status="published",
    )
    session.add(reserve_b)
    session.flush()

    link_ab = DutyReserveLink(primary_assignment_id=primary_a.id, reserve_assignment_id=reserve_b.id)
    session.add(link_ab)
    session.flush()

    # Future shift where C is currently primary — this is the slot A gets rolled onto.
    future_shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 11),
        start_time="08:00", end_time="17:00",
    )
    session.add(future_shift)
    session.flush()

    primary_c = DutyAssignment(
        soldier_id=soldier_c.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=future_shift.start_date, end_date=future_shift.end_date,
        duty_shift_id=future_shift.id, is_reserve=False, status="published",
    )
    session.add(primary_c)
    session.flush()
    session.commit()

    preview = svc.preview_gimelim(
        session,
        shift_id=current_shift.id,
        primary_assignment_id=primary_a.id,
        rest_days=1,
        reason="test reason",
        actor_id=soldier_a.id,
    )
    assert preview.future_assignment is not None, "expected a future slot to be found"
    assert preview.future_assignment.demoted_assignment_id == primary_c.id

    result = svc.commit_gimelim(
        session,
        shift_id=current_shift.id,
        preview_token=preview.preview_token,
        actor_id=soldier_a.id,
    )
    assert result.future_primary_assignment_id is not None

    a_new = session.get(DutyAssignment, result.future_primary_assignment_id)
    assert a_new is not None
    assert a_new.start_time == "08:00"
    assert a_new.end_time == "17:00"
