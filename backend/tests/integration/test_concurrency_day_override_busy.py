"""C14 (audit inventory S5/A6) — a covering soldier double-booked by day overrides.

Product rule (user decision, Task 6): a day override makes its covering
(effective) soldier busy for that day. A second override or swap must not
make the same soldier the effective soldier of another duty on that day.

``assignments.set_day_override`` (also reached from ``swaps._apply_cover``
when a swap is finalized) checks ``_day_busy``. Before the fix:

* sequentially: ``_day_busy`` looked only at nominal
  ``duty_assignments.soldier_id`` and ignored ``duty_day_overrides``, so a
  soldier already covering duty A on day d could be made the cover of duty B
  on day d;
* concurrently: even with overrides counted, nothing serialized two
  transactions that name the same covering soldier for the same day (each
  locks only its own assignment / swap request), so both could pass the
  check before either committed.

Fixed: ``_day_busy`` counts overrides whose effective soldier is the
candidate (on a non-cancelled assignment), and ``set_day_override`` locks the
candidate soldier row (``FOR NO KEY UPDATE``) before the check. Lock order:
(swap request ->) covering soldier -> assignment -> projection.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import DutyAssignment, DutyDayOverride, DutyLocation, DutyType, SoldierExemption, SwapRequest
from app.services import assignments as assignments_service
from app.services import swaps as swaps_service
from tests.helpers import create_node, create_soldier

_DAY = date.today() + timedelta(days=20)


def _two_duties(session, prefix: str, node_id=None):
    """Two one-day published duties on _DAY with different nominal soldiers,
    plus a free covering soldier and an admin."""
    dt = DutyType(name=f"{prefix}-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"{prefix}-loc")
    session.add_all([dt, loc])
    session.flush()
    n1 = create_soldier(session, personal_number=f"{prefix}-n1", hierarchy_node_id=node_id)
    n2 = create_soldier(session, personal_number=f"{prefix}-n2", hierarchy_node_id=node_id)
    cover = create_soldier(session, personal_number=f"{prefix}-c", hierarchy_node_id=node_id)
    admin = create_soldier(session, personal_number=f"{prefix}-admin", role="admin")
    duties = []
    for nominal in (n1, n2):
        a = DutyAssignment(
            soldier_id=nominal.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=_DAY, end_date=_DAY + timedelta(days=1), status="published", is_reserve=False,
        )
        session.add(a)
        duties.append(a)
    session.flush()
    return duties[0], duties[1], cover, admin, n1, n2


def _override_count(session, soldier_id) -> int:
    session.expire_all()
    return session.execute(
        select(func.count()).select_from(DutyDayOverride).where(
            DutyDayOverride.effective_soldier_id == soldier_id, DutyDayOverride.date == _DAY,
        )
    ).scalar_one()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C14: _day_busy ignores overrides")
def test_override_makes_the_covering_soldier_busy_for_that_day(admin_session):
    a1, a2, cover, admin, _n1, _n2 = _two_duties(admin_session, "c14-seq")
    assignments_service.set_day_override(
        admin_session, assignment=a1, date=_DAY, effective_soldier_id=cover.id, reason="manual_edit",
        actor_id=admin.id,
    )
    error = None
    try:
        assignments_service.set_day_override(
            admin_session, assignment=a2, date=_DAY, effective_soldier_id=cover.id, reason="manual_edit",
            actor_id=admin.id,
        )
    except assignments_service.AssignmentError as exc:
        error = str(exc)
    assert error == "overlap", "a soldier covering one duty by override was made the cover of another that day"
    # Re-setting the same assignment's own override is not a conflict.
    assignments_service.set_day_override(
        admin_session, assignment=a1, date=_DAY, effective_soldier_id=cover.id, reason="replacement",
        actor_id=admin.id,
    )


def test_override_on_a_cancelled_duty_does_not_make_the_soldier_busy(admin_session):
    a1, a2, cover, admin, _n1, _n2 = _two_duties(admin_session, "c14-cancel")
    assignments_service.set_day_override(
        admin_session, assignment=a1, date=_DAY, effective_soldier_id=cover.id, reason="manual_edit",
        actor_id=admin.id,
    )
    a1.status = "cancelled"
    admin_session.flush()
    assignments_service.set_day_override(
        admin_session, assignment=a2, date=_DAY, effective_soldier_id=cover.id, reason="manual_edit",
        actor_id=admin.id,
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C14: check_soldier_for_assignment ignores overrides")
def test_swap_eligibility_treats_a_covered_day_as_busy(admin_session):
    from app.services.eligibility import check_soldier_for_assignment

    a1, a2, cover, admin, _n1, _n2 = _two_duties(admin_session, "c14-elig")
    assert check_soldier_for_assignment(admin_session, cover.id, a2.id)[0] is True
    assignments_service.set_day_override(
        admin_session, assignment=a1, date=_DAY, effective_soldier_id=cover.id, reason="replacement",
        actor_id=admin.id,
    )
    eligible, reason, _warning = check_soldier_for_assignment(admin_session, cover.id, a2.id)
    assert eligible is False
    assert reason == "שיבוץ קיים בתאריכים אלו"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C14: concurrent overrides double-book the cover")
def test_concurrent_overrides_cannot_double_book_one_covering_soldier(race, admin_session):
    a1, a2, cover, admin, _n1, _n2 = _two_duties(admin_session, "c14-race")
    admin_session.commit()
    ids = {"a1": a1.id, "a2": a2.id, "cover": cover.id, "admin": admin.id}
    after_busy_check = race.rendezvous(2, "both passed the busy check")

    def override(key):
        def _call():
            s = race.session()
            a = s.get(DutyAssignment, ids[key])
            # The exemption read runs right after the _day_busy check.
            race.pause_after_select(s, SoldierExemption, after_busy_check.wait)
            assignments_service.set_day_override(
                s, assignment=a, date=_DAY, effective_soldier_id=ids["cover"], reason="manual_edit",
                actor_id=ids["admin"],
            )
            s.commit()
        return _call

    outcomes = race.run(override("a1"), override("a2"))

    for o in outcomes:
        if not o.ok and not isinstance(o.error, assignments_service.AssignmentError):
            raise RuntimeError(f"override crashed: {o.error!r}") from o.error
    count = _override_count(admin_session, ids["cover"])
    assert count == 1, f"covering soldier is effective on {count} duties on one day; outcomes={outcomes}"
    loser = next(o for o in outcomes if not o.ok)
    assert str(loser.error) == "overlap"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C14: concurrent swap finalizations double-book the cover")
def test_concurrent_swap_finalizations_cannot_double_book_one_candidate(race, admin_session):
    from app.services.settings_loader import set_setting

    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    node = create_node(admin_session, level="unit", name="c14-swap-unit")
    a1, a2, cover, _admin, n1, n2 = _two_duties(admin_session, "c14-swap", node_id=node.id)
    requests = []
    for nominal, a in ((n1, a1), (n2, a2)):
        req = swaps_service.create_request(
            admin_session, requesting_soldier_id=nominal.id, duty_assignment_id=a.id,
            target_soldier_id=None, target_soldier_ids=[cover.id], reason=None, open_to_marketplace=False,
        )
        requests.append(req.id)
    admin_session.commit()
    cover_id = cover.id
    after_busy_check = race.rendezvous(2, "both finalizations passed the busy check")

    def claim(request_id):
        def _call():
            s = race.session()
            race.pause_after_select(s, SoldierExemption, after_busy_check.wait)
            swaps_service.claim_request(s, request_id=request_id, covering_soldier_id=cover_id, actor_id=cover_id)
            s.commit()
        return _call

    outcomes = race.run(claim(requests[0]), claim(requests[1]))

    for o in outcomes:
        if not o.ok and not isinstance(o.error, swaps_service.SwapError):
            raise RuntimeError(f"claim crashed: {o.error!r}") from o.error
    count = _override_count(admin_session, cover_id)
    statuses = admin_session.execute(
        select(SwapRequest.status).where(SwapRequest.id.in_(requests))
    ).scalars().all()
    assert count == 1, f"candidate covers {count} duties on one day; statuses={statuses}; outcomes={outcomes}"
    assert sorted(statuses) == ["applied", "open"]
    loser = next(o for o in outcomes if not o.ok)
    assert str(loser.error) == "cover_blocked:overlap"
