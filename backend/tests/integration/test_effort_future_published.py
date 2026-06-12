"""Effort must count ALL published commitments — including assignments published
for dates AFTER the planning window (schedules are often published months ahead).

Regression: previously the effort-history window stopped at planning_start, so a
soldier already booked far into the future showed zero effort and kept getting
new duties. effort_history_horizon extends the window past the latest published
assignment so those future commitments count.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier
from app.services.algorithm_bridge import effort_history_horizon
from app.services.effort_score import compute_effort_data
from tests.helpers import create_soldier


def _enrol(session: Session, s: Soldier, when: date) -> None:
    s.enrolled_at = when
    session.add(s)
    session.commit()


def test_future_published_assignments_count_toward_effort(admin_session: Session) -> None:
    a = create_soldier(admin_session, personal_number="5900001", role="soldier")
    b = create_soldier(admin_session, personal_number="5900002", role="soldier")
    _enrol(admin_session, a, date(2025, 1, 1))
    _enrol(admin_session, b, date(2025, 1, 1))

    dt = DutyType(name="שמירה-fut", score_per_day=Decimal("2.00"))
    loc = DutyLocation(name="מוצב-fut")
    admin_session.add_all([dt, loc])
    admin_session.commit()

    # The new duty we are about to plan starts "next week"…
    planning_start = date(2026, 1, 15)
    # …but soldier A is ALREADY published for a duty in a LATER quarter.
    admin_session.add(DutyAssignment(
        soldier_id=a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 5, 1), end_date=date(2026, 5, 10), status="published",
    ))
    admin_session.commit()

    reset_date = date(2025, 1, 1)
    soldiers = [a, b]

    # The horizon extends past the future-dated published assignment.
    horizon = effort_history_horizon(admin_session, planning_start=planning_start)
    assert horizon == date(2026, 5, 11)

    # With the extended horizon, A's future commitment counts → A has effort, B does not.
    eff = compute_effort_data(
        admin_session, soldiers=soldiers,
        planning_start=horizon, planning_end=horizon, reset_date=reset_date,
    )
    assert eff[a.id].effort_score > Decimal("0")
    assert eff[b.id].effort_score == Decimal("0")
    assert eff[a.id].effort_score > eff[b.id].effort_score

    # Sanity: the OLD behaviour (window stopping at planning_start) misses it entirely.
    eff_old = compute_effort_data(
        admin_session, soldiers=soldiers,
        planning_start=planning_start, planning_end=planning_start, reset_date=reset_date,
    )
    assert eff_old[a.id].effort_score == Decimal("0")


def test_horizon_falls_back_to_planning_start_without_future_work(admin_session: Session) -> None:
    s = create_soldier(admin_session, personal_number="5900003", role="soldier")
    _enrol(admin_session, s, date(2025, 1, 1))
    planning_start = date(2030, 1, 1)  # far future — no published work at/after this
    assert effort_history_horizon(admin_session, planning_start=planning_start) == planning_start
