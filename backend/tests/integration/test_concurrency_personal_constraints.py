"""C5 — personal-constraint cap bypass (audit inventory K1).

``submit_constraint`` sums the soldier's pending + approved constraint days in
the reset period (``remaining_days``) and rejects the request when
``used + requested > cap_days``. Nothing locks the soldier or the constraint
set, so two concurrent submissions each see the other's days as unused.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. request A and request B each read used=0 for the period (cap 3 days);
  2. both meet at a rendezvous right after ``remaining_days`` returns;
  3. both insert a 2-day constraint and commit (4 days > cap 3).

Fixed (Task 3): ``submit_constraint`` locks the soldier row
(``FOR NO KEY UPDATE``) before ``remaining_days``. B blocks until A commits,
A's rendezvous times out, and B then counts A's days and fails with
``cap_exceeded``.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import PersonalConstraint, SystemSetting
from app.services import constraints as constraints_service
from tests.helpers import create_soldier

_CAP_DAYS = 3


def _next_quarter_start(today: date) -> date:
    month = (today.month - 1) // 3 * 3 + 4
    return date(today.year + (month > 12), (month - 1) % 12 + 1, 1)


def _seed(session):
    session.add(SystemSetting(key="constraints.personal_cap_days", value=_CAP_DAYS))
    session.add(SystemSetting(key="constraints.reset_period", value="quarter"))
    soldier = create_soldier(session, personal_number="race-cap-soldier")
    session.commit()
    # Both requests sit inside one future quarter, so they share one cap period.
    base = _next_quarter_start(date.today())
    return soldier.id, base


def _race_submissions(race, monkeypatch, soldier_id, windows):
    after_cap_read = race.rendezvous(2, "both submissions read the used-days total")
    real_remaining_days = constraints_service.remaining_days

    def remaining_then_wait(session, **kwargs):
        result = real_remaining_days(session, **kwargs)
        after_cap_read.wait()
        return result

    monkeypatch.setattr(constraints_service, "remaining_days", remaining_then_wait)

    def submit(start, end):
        def _call():
            s = race.session()
            c = constraints_service.submit_constraint(
                s, soldier_id=soldier_id, start_date=start, end_date=end, reason="race", actor_id=soldier_id,
            )
            s.commit()
            return c.id
        return _call

    return race.run(*(submit(start, end) for start, end in windows))


def _active_days(session, soldier_id) -> int:
    session.expire_all()
    rows = session.execute(select(PersonalConstraint).where(
        PersonalConstraint.soldier_id == soldier_id,
        PersonalConstraint.status.in_(["pending_commander", "pending_duty_manager", "approved"]),
    )).scalars().all()
    return sum((r.end_date - r.start_date).days + 1 for r in rows)


def test_concurrent_submissions_cannot_exceed_cap(race, admin_session, monkeypatch):
    soldier_id, base = _seed(admin_session)
    windows = [(base, base + timedelta(days=1)), (base + timedelta(days=2), base + timedelta(days=3))]

    outcomes = _race_submissions(race, monkeypatch, soldier_id, windows)

    for outcome in outcomes:
        if not outcome.ok and not isinstance(outcome.error, constraints_service.ConstraintError):
            raise RuntimeError(f"request crashed: {outcome.error!r}") from outcome.error
    assert any(o.ok for o in outcomes), outcomes
    days = _active_days(admin_session, soldier_id)
    assert days <= _CAP_DAYS, f"cap is {_CAP_DAYS} days but {days} days were committed; outcomes={outcomes}"
    loser = next(o for o in outcomes if not o.ok)
    assert str(loser.error) == "cap_exceeded"


def test_concurrent_submissions_within_cap_both_succeed(race, admin_session, monkeypatch):
    """Control: two 1-day requests (2 days total, cap 3) both succeed."""
    soldier_id, base = _seed(admin_session)
    windows = [(base, base), (base + timedelta(days=2), base + timedelta(days=2))]

    outcomes = _race_submissions(race, monkeypatch, soldier_id, windows)

    assert all(o.ok for o in outcomes), outcomes
    assert _active_days(admin_session, soldier_id) == 2
