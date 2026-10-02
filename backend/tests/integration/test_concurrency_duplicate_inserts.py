"""C17 — concurrent duplicate inserts surface as IntegrityError / HTTP 500.

Several services check "does the row already exist?" with an unlocked SELECT
and then INSERT. A unique constraint catches the loser, but nothing translates
the error, so the second request gets an unhandled 500 instead of the domain
answer the sequential path gives:

* ``assignments.set_day_override`` — ``uq_duty_day_overrides_assignment_date``
  (sequentially the second call *updates* the existing override);
* ``swaps.take_free`` — ``uq_swap_requests_one_open_per_requester_duty``
  (sequentially: ``already_pending``);
* ``no_show.mark_no_show`` — ``uq_duty_no_shows_assignment``
  (sequentially: ``already_marked``);
* ``reserves.relink_reserve`` — ``uq_reserve_links_primary``
  (sequentially the second call replaces the link).

Each schedule: two independent sessions both run the existence SELECT, meet
right after it, then both insert and commit.

Fixed (Task 4): ``set_day_override``, ``mark_no_show`` and ``relink_reserve``
lock the duty assignment (``FOR NO KEY UPDATE``) before the existence check,
so the second request sees the first's row and gets the sequential answer.
``take_free`` translates the unique violation to ``already_pending``, as
``create_request`` already does (the competing writer may be a
``create_request`` that takes no assignment lock).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyLocation,
    DutyNoShow,
    DutyReserveLink,
    DutyType,
    SwapRequest,
)
from app.services import assignments as assignments_service
from app.services import no_show as no_show_service
from app.services import reserves as reserves_service
from app.services import swaps as swaps_service
from tests.helpers import create_soldier


def _assignment(session, soldier_id, *, start, days=4, is_reserve=False, tag=""):
    dt = DutyType(name=f"race-dup-type-{tag}-{soldier_id}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"race-dup-loc-{tag}-{soldier_id}")
    session.add_all([dt, loc])
    session.flush()
    # algorithm_draft keeps the score projection out of these schedules (its
    # own first-insert race, O1, is tested separately).
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id, start_date=start,
        end_date=start + timedelta(days=days), status="algorithm_draft", is_reserve=is_reserve,
    )
    session.add(a)
    session.flush()
    return a


def _race(race, entity, call_a, call_b):
    after_read = race.rendezvous(2, f"both requests read {entity.__tablename__}")

    def wrap(call):
        def _run():
            s = race.session()
            race.pause_after_select(s, entity, after_read.wait)
            result = call(s)
            s.commit()
            return result
        return _run

    return race.run(wrap(call_a), wrap(call_b))


def _assert_no_db_error(outcomes, domain_error):
    for outcome in outcomes:
        assert outcome.ok or isinstance(outcome.error, domain_error), (
            f"a request failed with a database error instead of a domain answer: {outcomes}"
        )


def _count(session, model, **where):
    session.expire_all()
    return session.execute(
        select(func.count()).select_from(model).filter_by(**where)
    ).scalar_one()


def test_concurrent_day_overrides_for_one_day_both_succeed(race, admin_session):
    soldier = create_soldier(admin_session, personal_number="race-dup-ov")
    a = _assignment(admin_session, soldier.id, start=date.today() + timedelta(days=20), tag="ov")
    admin_session.commit()
    day = a.start_date + timedelta(days=1)

    def override(reason):
        return lambda s: assignments_service.set_day_override(
            s, assignment=s.get(DutyAssignment, a.id), date=day, effective_soldier_id=None, reason=reason,
        ).reason

    outcomes = _race(race, DutyDayOverride, override("cancelled"), override("manual_edit"))

    _assert_no_db_error(outcomes, assignments_service.AssignmentError)
    assert all(o.ok for o in outcomes), outcomes
    assert _count(admin_session, DutyDayOverride, duty_assignment_id=a.id) == 1


def test_concurrent_take_free_of_one_duty_yields_already_pending(race, admin_session, monkeypatch):
    owner = create_soldier(admin_session, personal_number="race-dup-tf-owner")
    c1 = create_soldier(admin_session, personal_number="race-dup-tf-c1")
    c2 = create_soldier(admin_session, personal_number="race-dup-tf-c2")
    a = _assignment(admin_session, owner.id, start=date.today() + timedelta(days=20), tag="tf")
    admin_session.commit()
    # Eligibility and hierarchy rules are not under test; the race is on the
    # one-open-request-per-duty invariant.
    monkeypatch.setattr(swaps_service, "check_soldier_for_assignment", lambda *a, **k: (True, None, None))
    monkeypatch.setattr(swaps_service, "_enforce_hierarchy_level_restriction", lambda *a, **k: None)

    def take(covering_id):
        return lambda s: swaps_service.take_free(s, assignment_id=a.id, covering_soldier_id=covering_id)[0].id

    outcomes = _race(race, SwapRequest, take(c1.id), take(c2.id))

    _assert_no_db_error(outcomes, swaps_service.SwapError)
    assert _count(admin_session, SwapRequest, duty_assignment_id=a.id, status="open") == 1
    assert sorted(str(o.error) for o in outcomes if not o.ok) == ["already_pending"]


def test_concurrent_no_show_marks_yield_already_marked(race, admin_session):
    soldier = create_soldier(admin_session, personal_number="race-dup-ns")
    manager = create_soldier(admin_session, personal_number="race-dup-ns-dm", role="admin")
    a = _assignment(admin_session, soldier.id, start=date.today() - timedelta(days=10), tag="ns")
    admin_session.commit()

    def mark(s):
        return no_show_service.mark_no_show(s, duty_assignment_id=a.id, marked_by=manager.id, note="לא הגיע").id

    outcomes = _race(race, DutyNoShow, mark, mark)

    _assert_no_db_error(outcomes, no_show_service.NoShowError)
    assert _count(admin_session, DutyNoShow, duty_assignment_id=a.id) == 1
    assert sorted(str(o.error) for o in outcomes if not o.ok) == ["already_marked"]


def test_concurrent_relinks_of_one_primary_both_succeed(race, admin_session):
    start = date.today() + timedelta(days=20)
    primary = _assignment(admin_session, create_soldier(admin_session, personal_number="race-dup-rl-p").id,
                          start=start, tag="rlp")
    r1 = _assignment(admin_session, create_soldier(admin_session, personal_number="race-dup-rl-r1").id,
                     start=start, is_reserve=True, tag="rl1")
    r2 = _assignment(admin_session, create_soldier(admin_session, personal_number="race-dup-rl-r2").id,
                     start=start, is_reserve=True, tag="rl2")
    admin_session.commit()

    def relink(reserve_id):
        return lambda s: reserves_service.relink_reserve(
            s, primary_assignment=s.get(DutyAssignment, primary.id), reserve_assignment_id=reserve_id,
        ).reserve_assignment_id

    outcomes = _race(race, DutyReserveLink, relink(r1.id), relink(r2.id))

    _assert_no_db_error(outcomes, reserves_service.ReserveError)
    assert all(o.ok for o in outcomes), outcomes
    assert _count(admin_session, DutyReserveLink, primary_assignment_id=primary.id) == 1
