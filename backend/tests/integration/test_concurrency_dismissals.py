"""C16/D1 — overlapping dismissals on one assignment (audit inventory D1).

``reserves.dismiss_primary`` (and ``dismiss_reserve``) read the assignment's
existing dismissals, reject an overlapping range, then insert. Nothing locks
the assignment or constrains ``duty_dismissals`` against overlap.

Schedule reproduced here (two independent sessions = two managers dismissing
the same soldier for overlapping days):
  1. both requests read the assignment's dismissals (none) and meet right
     after that SELECT;
  2. both insert their dismissal and commit.
The assignment ends up with two overlapping dismissals, and the soldier gets
two "dismissed" notifications for the same days.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ScoreProjectionDirtyBucket,
    ScoreProjectionQuarterTotal,
    SoldierScoreProjection,
)
from app.services import reserves as reserves_service
from tests.helpers import create_soldier

_START = date.today() + timedelta(days=30)


def _seed(session):
    soldier = create_soldier(session, personal_number="race-dismiss-s")
    admin = create_soldier(session, personal_number="race-dismiss-admin", role="admin")
    dt = DutyType(name="race-dismiss-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-dismiss-loc")
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=_START, end_date=_START + timedelta(days=8), status="published", is_reserve=False,
    )
    session.add(assignment)
    # Pre-create the projection rows both refreshes would otherwise INSERT for
    # the first time (the first-insert race O1 is tested separately).
    quarter = date(_START.year, (_START.month - 1) // 3 * 3 + 1, 1)
    zero = Decimal("0")
    session.add_all([
        ScoreProjectionQuarterTotal(
            quarter_start=quarter, projection_version="1", raw_day_count=0, effective_weighted_days=zero,
            duty_score=zero, adjustment_score=zero, total_score=zero,
        ),
        ScoreProjectionDirtyBucket(soldier_id=soldier.id, quarter_start=quarter, status="current"),
        SoldierScoreProjection(soldier_id=soldier.id, projection_version="1", duty_score=zero,
                               adjustment_score=zero, cumulative_score=zero),
    ])
    session.commit()
    return assignment.id, admin.id


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C16/D1: dismissal overlap check is not serialized")
def test_concurrent_overlapping_dismissals_record_only_one(race, admin_session):
    assignment_id, admin_id = _seed(admin_session)
    after_overlap_read = race.rendezvous(2, "both read the existing dismissals")

    def dismiss(offset_from, offset_to):
        def _call():
            s = race.session()
            assignment = s.get(DutyAssignment, assignment_id)
            race.pause_after_select(s, DutyDismissal, after_overlap_read.wait)
            d = reserves_service.dismiss_primary(
                s, assignment=assignment, from_date=_START + timedelta(days=offset_from),
                to_date=_START + timedelta(days=offset_to), reason=None, actor_id=admin_id,
            )
            s.commit()
            return d.id
        return _call

    outcomes = race.run(dismiss(1, 3), dismiss(2, 4))

    for outcome in outcomes:
        if not outcome.ok and not isinstance(outcome.error, reserves_service.ReserveError):
            raise RuntimeError(f"dismissal crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    count = admin_session.execute(
        select(func.count()).select_from(DutyDismissal).where(DutyDismissal.duty_assignment_id == assignment_id)
    ).scalar_one()
    assert count == 1, f"{count} overlapping dismissals committed; outcomes={outcomes}"
    loser = next(o for o in outcomes if not o.ok)
    assert str(loser.error) == "overlapping_dismissal"
