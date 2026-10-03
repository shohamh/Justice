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

Fixed (Task 4): ``dismiss_primary`` and ``dismiss_reserve`` lock the assignment
row (``FOR NO KEY UPDATE``) before reading its dismissals. The second request
blocks, the first's rendezvous times out and it commits, and the second then
sees the committed dismissal and fails with ``overlapping_dismissal``.
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


def test_covered_reserve_dismissal_and_primary_dismissal_do_not_deadlock(race, admin_session):
    """``dismiss_reserve(R, covering_reserve_id=R2)`` locks R, refreshes the
    score projection (locking the quarter-total row) and only then relinks
    R's primaries, locking each primary P. ``dismiss_primary(P)`` locks P and
    then refreshes the projection (quarter total). Opposite order on P and the
    quarter total.

    Schedule: the reserve dismissal holds the quarter total; the primary
    dismissal holds P; each then waits for the other's lock.

    Fixed: with a covering reserve, dismiss_reserve locks R's linked
    primaries in id order right after R and before the projection refresh
    (reserve -> primaries -> projection). The primary dismissal then blocks
    on P before the reserve side reaches the quarter total, so the reserve
    side's wait times out, it commits, and the primary dismissal runs after."""
    from app.db.models import DutyReserveLink

    admin = create_soldier(admin_session, personal_number="race-dr-admin", role="admin")
    dt = DutyType(name="race-dr-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-dr-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    def assignment(pn, is_reserve):
        s = create_soldier(admin_session, personal_number=pn)
        a = DutyAssignment(soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id, start_date=_START,
                           end_date=_START + timedelta(days=8), status="published", is_reserve=is_reserve)
        admin_session.add(a)
        admin_session.flush()
        return a

    primary = assignment("race-dr-p", False)
    reserve = assignment("race-dr-r", True)
    cover = assignment("race-dr-r2", True)
    admin_session.add(DutyReserveLink(primary_assignment_id=primary.id, reserve_assignment_id=reserve.id,
                                      hierarchy_distance=0))
    admin_session.add(ScoreProjectionQuarterTotal(
        quarter_start=date(_START.year, (_START.month - 1) // 3 * 3 + 1, 1), projection_version="1",
        raw_day_count=0, effective_weighted_days=Decimal("0"), duty_score=Decimal("0"),
        adjustment_score=Decimal("0"), total_score=Decimal("0"),
    ))
    admin_session.commit()
    primary_id, reserve_id, cover_id, admin_id = primary.id, reserve.id, cover.id, admin.id

    reserve_side_holds_total = race.signal("reserve dismissal holds the quarter total")
    primary_side_holds_primary = race.signal("primary dismissal holds the primary")

    def dismiss_reserve():
        s = race.session()
        r = s.get(DutyAssignment, reserve_id)

        def _after_total_lock():
            reserve_side_holds_total.set()
            primary_side_holds_primary.wait()

        race.pause_after_select(s, ScoreProjectionQuarterTotal, _after_total_lock)
        d, _ = reserves_service.dismiss_reserve(
            s, assignment=r, from_date=_START + timedelta(days=1), to_date=_START + timedelta(days=2),
            reason=None, actor_id=admin_id, covering_reserve_id=cover_id,
        )
        s.commit()
        return d.id

    def dismiss_primary():
        reserve_side_holds_total.wait()
        s = race.session()
        p = s.get(DutyAssignment, primary_id)
        # The dismissal-overlap read runs right after dismiss_primary locks P.
        race.pause_after_select(s, DutyDismissal, primary_side_holds_primary.set)
        d = reserves_service.dismiss_primary(
            s, assignment=p, from_date=_START + timedelta(days=4), to_date=_START + timedelta(days=5),
            reason=None, actor_id=admin_id,
        )
        s.commit()
        return d.id

    outcomes = race.run(dismiss_reserve, dismiss_primary)

    assert all(o.ok for o in outcomes), f"outcomes={outcomes}"
    admin_session.expire_all()
    link = admin_session.execute(
        select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == primary_id)
    ).scalar_one()
    assert link.reserve_assignment_id == cover_id


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="dismiss_reserve locks a newly linked primary after the projection")
def test_reserve_dismissal_with_a_primary_linked_mid_request_does_not_deadlock(race, admin_session):
    """``dismiss_reserve(R, covering_reserve_id)`` locks R's linked primaries
    from the links visible when that statement runs. A primary P2 linked to R
    by a concurrent ``relink_reserve`` that commits right after is not in that
    set; ``dismiss_reserve`` re-reads the links after the projection refresh
    and locks P2 then (inside ``relink_reserve``), after the quarter total.
    ``dismiss_primary(P2)`` locks P2 and then the quarter total: a cycle.

    Schedule (three sessions): A locks R and its primaries {P1}; B links P2 to
    R and commits; C locks P2 (dismiss_primary); A takes the projection rows
    and reaches P2; C reaches the projection.

    Fixed: ``dismiss_reserve`` relinks (or reallocates) before refreshing the
    projection, so every primary lock, including one for a newly linked
    primary, is taken before any projection lock."""
    from app.db.models import DutyReserveLink

    admin = create_soldier(admin_session, personal_number="race-dr3-admin", role="admin")
    dt = DutyType(name="race-dr3-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-dr3-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    def assignment(pn, is_reserve):
        s = create_soldier(admin_session, personal_number=pn)
        a = DutyAssignment(soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id, start_date=_START,
                           end_date=_START + timedelta(days=8), status="published", is_reserve=is_reserve)
        admin_session.add(a)
        admin_session.flush()
        return a

    p1 = assignment("race-dr3-p1", False)
    p2 = assignment("race-dr3-p2", False)
    reserve = assignment("race-dr3-r", True)
    cover = assignment("race-dr3-r2", True)
    admin_session.add(DutyReserveLink(primary_assignment_id=p1.id, reserve_assignment_id=reserve.id,
                                      hierarchy_distance=0))
    admin_session.add(ScoreProjectionQuarterTotal(
        quarter_start=date(_START.year, (_START.month - 1) // 3 * 3 + 1, 1), projection_version="1",
        raw_day_count=0, effective_weighted_days=Decimal("0"), duty_score=Decimal("0"),
        adjustment_score=Decimal("0"), total_score=Decimal("0"),
    ))
    admin_session.commit()
    p2_id, reserve_id, cover_id, admin_id = p2.id, reserve.id, cover.id, admin.id

    a_locked_primaries = race.signal("reserve dismissal locked R's primaries")
    b_linked = race.signal("P2 linked to R and committed")
    c_holds_p2 = race.signal("primary dismissal holds P2")
    a_holds_projection = race.signal("reserve dismissal holds the projection rows")

    def dismiss_reserve():
        s = race.session()
        r = s.get(DutyAssignment, reserve_id)

        def _after_primary_locks():
            a_locked_primaries.set()
            b_linked.wait()
            c_holds_p2.wait()

        race.pause_after_select(s, DutyDismissal, _after_primary_locks)
        race.pause_after_select(s, ScoreProjectionQuarterTotal, a_holds_projection.set)
        d, _ = reserves_service.dismiss_reserve(
            s, assignment=r, from_date=_START + timedelta(days=1), to_date=_START + timedelta(days=2),
            reason=None, actor_id=admin_id, covering_reserve_id=cover_id,
        )
        s.commit()
        return d.id

    def link_p2():
        a_locked_primaries.wait()
        s = race.session()
        try:
            reserves_service.relink_reserve(
                s, primary_assignment=s.get(DutyAssignment, p2_id), reserve_assignment_id=reserve_id,
                actor_id=admin_id,
            )
            s.commit()
        finally:
            b_linked.set()

    def dismiss_p2():
        b_linked.wait()
        s = race.session()

        def _after_p2_lock():
            c_holds_p2.set()
            a_holds_projection.wait()

        race.pause_after_select(s, DutyDismissal, _after_p2_lock)
        d = reserves_service.dismiss_primary(
            s, assignment=s.get(DutyAssignment, p2_id), from_date=_START + timedelta(days=4),
            to_date=_START + timedelta(days=5), reason=None, actor_id=admin_id,
        )
        s.commit()
        return d.id

    outcomes = race.run(dismiss_reserve, link_p2, dismiss_p2)

    assert all(o.ok for o in outcomes), f"outcomes={outcomes}"
    admin_session.expire_all()
    link = admin_session.execute(
        select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == p2_id)
    ).scalar_one()
    assert link.reserve_assignment_id == cover_id
