from datetime import date
from decimal import Decimal

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType
from app.services.scoring import effective_duty_spans
from tests.helpers import create_soldier


def test_dismissed_days_are_dropped_from_effective_spans(admin_session):
    dt = DutyType(name="שמירה-dism", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-dism")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="dism01")

    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 8),
        status="published", is_reserve=False,
    )
    admin_session.add(a)
    admin_session.flush()
    admin_session.add(DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 6, 3), dismissed_to=date(2026, 6, 4),
    ))
    admin_session.commit()

    spans = effective_duty_spans(admin_session, soldier_ids={s.id})
    covered_days = set()
    for sp in spans:
        d = sp["start_date"]
        while d < sp["end_date"]:
            covered_days.add(d)
            d += __import__("datetime").timedelta(days=1)

    assert date(2026, 6, 3) not in covered_days
    assert date(2026, 6, 4) not in covered_days
    assert date(2026, 6, 1) in covered_days
    assert date(2026, 6, 7) in covered_days
