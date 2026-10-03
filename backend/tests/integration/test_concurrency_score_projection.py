"""O1 — score-projection refresh races (found during Task 2, see report §4.1).

Every assignment write refreshes the score projection in the same transaction
(``refresh_projection_for_change``). Three helpers there do select-then-insert
or read-compute-write without a lock:

* ``_upsert_quarter_total``: ``session.get`` the quarter-total row, INSERT it if
  missing. Two first writes in a quarter both INSERT and one request dies on
  ``score_projection_quarter_total_pkey`` (HTTP 500).
* the same function computes the quarter's sums *before* it writes the row, so
  two concurrent refreshes for different soldiers each store a total that
  leaves out the other's rows (lost update; the total drifts from its rows).
* ``_mark_dirty_bucket`` (and ``_upsert_soldier_total``) do the same
  select-then-insert per soldier/quarter. Two writes for one soldier that do
  not take the soldier lock (two dismissals on different assignments) die on
  ``uq_score_projection_dirty_bucket``.

Schedules (two independent sessions = two requests), each meeting right after
the contested read.

Fixed (Task 4): the three helpers create the row with ``INSERT ... ON CONFLICT
DO NOTHING`` and then lock it ``FOR UPDATE`` *before* computing the new values
(``_lock_or_create_row``). The second writer waits for the first to commit,
so the first's rendezvous times out, and the second then recomputes from the
committed rows.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    ScoreProjectionDirtyBucket,
    ScoreProjectionQuarterTotal,
    SoldierQuarterScoreProjection,
)
from app.services import assignments as assignments_service
from app.services import reserves as reserves_service
from tests.helpers import create_soldier

_START = date.today() + timedelta(days=30)
_QUARTER = date(_START.year, (_START.month - 1) // 3 * 3 + 1, 1)
_ZERO = Decimal("0")


def _duty(session, tag):
    dt = DutyType(name=f"race-proj-{tag}-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"race-proj-{tag}-loc")
    session.add_all([dt, loc])
    session.flush()
    return dt.id, loc.id


def _quarter_total_row():
    return ScoreProjectionQuarterTotal(
        quarter_start=_QUARTER, projection_version="1", raw_day_count=0, effective_weighted_days=_ZERO,
        duty_score=_ZERO, adjustment_score=_ZERO, total_score=_ZERO,
    )


def _race_two_assignments(race, s1_id, s2_id, dt_id, loc_id):
    after_read = race.rendezvous(2, "both refreshes read the quarter total")

    def create(soldier_id):
        def _call():
            s = race.session()
            race.pause_after_select(s, ScoreProjectionQuarterTotal, after_read.wait)
            a = assignments_service.create_assignment(
                s, soldier_id=soldier_id, duty_type_id=dt_id, duty_location_id=loc_id,
                start_date=_START, end_date=_START + timedelta(days=2),
            )
            s.commit()
            return a.id
        return _call

    return race.run(create(s1_id), create(s2_id))


def test_first_two_writes_in_a_quarter_both_succeed(race, admin_session):
    s1 = create_soldier(admin_session, personal_number="race-proj-q1")
    s2 = create_soldier(admin_session, personal_number="race-proj-q2")
    dt_id, loc_id = _duty(admin_session, "first")
    admin_session.commit()

    outcomes = _race_two_assignments(race, s1.id, s2.id, dt_id, loc_id)

    assert all(o.ok for o in outcomes), outcomes


def test_concurrent_refreshes_keep_the_quarter_total_equal_to_its_rows(race, admin_session):
    s1 = create_soldier(admin_session, personal_number="race-proj-l1")
    s2 = create_soldier(admin_session, personal_number="race-proj-l2")
    dt_id, loc_id = _duty(admin_session, "lost")
    admin_session.add(_quarter_total_row())
    admin_session.commit()

    outcomes = _race_two_assignments(race, s1.id, s2.id, dt_id, loc_id)

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"refresh crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    total = admin_session.get(ScoreProjectionQuarterTotal, _QUARTER)
    rows_raw_days = admin_session.execute(
        select(func.coalesce(func.sum(SoldierQuarterScoreProjection.raw_day_count), 0))
        .where(SoldierQuarterScoreProjection.quarter_start == _QUARTER)
    ).scalar_one()
    assert rows_raw_days > 0
    assert total.raw_day_count == rows_raw_days, (
        f"quarter total raw_day_count={total.raw_day_count} but its rows sum to {rows_raw_days}"
    )


def test_first_two_refreshes_of_one_soldier_bucket_both_succeed(race, admin_session):
    soldier = create_soldier(admin_session, personal_number="race-proj-b")
    admin = create_soldier(admin_session, personal_number="race-proj-b-admin", role="admin")
    dt_id, loc_id = _duty(admin_session, "bucket")
    assignment_ids = []
    for offset in (0, 10):
        a = DutyAssignment(
            soldier_id=soldier.id, duty_type_id=dt_id, duty_location_id=loc_id,
            start_date=_START + timedelta(days=offset), end_date=_START + timedelta(days=offset + 4),
            status="published", is_reserve=False,
        )
        admin_session.add(a)
        admin_session.flush()
        assignment_ids.append(a.id)
    admin_session.add(_quarter_total_row())
    admin_session.commit()

    after_read = race.rendezvous(2, "both refreshes read the soldier's dirty bucket")

    def dismiss(assignment_id):
        def _call():
            s = race.session()
            assignment = s.get(DutyAssignment, assignment_id)
            race.pause_after_select(s, ScoreProjectionDirtyBucket, after_read.wait)
            d = reserves_service.dismiss_primary(
                s, assignment=assignment, from_date=assignment.start_date + timedelta(days=1),
                to_date=assignment.start_date + timedelta(days=2), reason=None, actor_id=admin.id,
            )
            s.commit()
            return d.id
        return _call

    outcomes = race.run(dismiss(assignment_ids[0]), dismiss(assignment_ids[1]))

    assert all(o.ok for o in outcomes), outcomes
    admin_session.expire_all()
    buckets = admin_session.execute(
        select(func.count()).select_from(ScoreProjectionDirtyBucket)
        .where(ScoreProjectionDirtyBucket.soldier_id == soldier.id)
    ).scalar_one()
    assert buckets == 1


def test_overlapping_multi_soldier_refreshes_do_not_deadlock(race, admin_session):
    """``refresh_projection_for_change`` locked, per soldier in id order, the
    dirty bucket, the soldier total and then the quarter total. A refresh of
    {S1, S2} holds the quarter total after S1 and then wants bucket(S2); a
    concurrent refresh of {S2} alone holds bucket(S2) and wants the quarter
    total. (For example ``set_day_override`` refreshing the nominal and the
    covering soldier while ``create_assignment`` refreshes the cover alone.)

    Fixed: every bucket, then every soldier total, then every quarter total is
    locked in a global order before any rebuild."""
    from app.services.score_projection import refresh_projection_for_change

    a = create_soldier(admin_session, personal_number="race-proj-il-a")
    b = create_soldier(admin_session, personal_number="race-proj-il-b")
    admin_session.add(_quarter_total_row())
    admin_session.commit()
    low, high = sorted([a.id, b.id], key=str)

    both_holds_total = race.signal("two-soldier refresh holds the quarter total")
    single_holds_bucket = race.signal("one-soldier refresh holds bucket(S2)")

    def refresh_both():
        s = race.session()

        def _after_total():
            both_holds_total.set()
            single_holds_bucket.wait()

        race.pause_after_select(s, ScoreProjectionQuarterTotal, _after_total)
        refresh_projection_for_change(s, soldier_ids={low, high}, affected_dates={_START})
        s.commit()

    def refresh_high():
        both_holds_total.wait()
        s = race.session()
        race.pause_after_select(s, ScoreProjectionDirtyBucket, single_holds_bucket.set)
        refresh_projection_for_change(s, soldier_ids={high}, affected_dates={_START})
        s.commit()

    outcomes = race.run(refresh_both, refresh_high)

    assert all(o.ok for o in outcomes), f"outcomes={outcomes}"
