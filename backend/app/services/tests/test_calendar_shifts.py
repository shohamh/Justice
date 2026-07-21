from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, text

from app.db.models import DutyLocation, DutyType
from app.services import calendar_shifts
from app.services.duty_config import create_duty_type
from app.services.shifts import create_shift


def _make_duty_type_and_location(session, name_suffix: str):
    dt = create_duty_type(session, name=f"dt_calshift_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_calshift_{name_suffix}")
    session.add(loc)
    session.flush()
    return dt, loc


def test_single_shift_with_missing_duty_type_gets_hash_color_not_black(admin_session):
    dt, loc = _make_duty_type_and_location(admin_session, "1")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    admin_session.commit()

    # Simulate a dangling reference: delete the duty type row directly,
    # leaving shift.duty_type_id orphaned. The FK is ON DELETE RESTRICT
    # (a duty type in use can't normally be deleted), so we briefly disable
    # the constraint-enforcement trigger to force the orphaned state that
    # can occur from historical data drift / out-of-band admin operations.
    admin_session.execute(text("ALTER TABLE duty_types DISABLE TRIGGER ALL"))
    try:
        admin_session.execute(delete(DutyType).where(DutyType.id == dt.id))
        admin_session.flush()
    finally:
        admin_session.execute(text("ALTER TABLE duty_types ENABLE TRIGGER ALL"))

    row = calendar_shifts.get_single_shift(admin_session, shift_id=shift.id)
    assert row is not None
    assert row["duty_type_color"] != ""
    assert row["duty_type_color"].startswith("hsl(")
