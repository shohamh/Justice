import uuid
from datetime import date, timedelta

import pytest

from app.db.models import PersonalConstraint, SoldierEnrollmentRequest
from app.services import constraints
from app.services.constraints import (
    ConstraintError,
    approve_constraint,
    cancel_constraint,
    get_approved_constraint_dates,
    list_constraints,
    reject_constraint,
    submit_constraint,
)
from tests.helpers import create_node, create_soldier

_PREFIX = str(uuid.uuid4())[:8]


def _pn(n: int) -> str:
    return f"{_PREFIX}-{n:04d}"


def test_submit_success(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(1))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.commit()
    assert c.status == "pending_commander"
    assert c.soldier_id == s.id


def test_submit_auto_approve(admin_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.constraints._get_setting_with_default",
        lambda session, key, default: False
        if key in ("constraints.require_commander_approval", "constraints.require_duty_manager_approval")
        else default,
    )
    s = create_soldier(admin_session, personal_number=_pn(2))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=s.id,
    )
    admin_session.commit()
    assert c.status == "approved"
    assert c.decided_by is None


def test_submit_cap_enforced(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(3))
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=15),
        reason="ארוך",
        actor_id=None,
    )
    admin_session.flush()
    with pytest.raises(ConstraintError, match="cap_exceeded"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date.today() + timedelta(days=20),
            end_date=date.today() + timedelta(days=21),
            reason="עוד",
            actor_id=None,
        )


def test_submit_cap_check_is_period_scoped_not_full_future_span(admin_session):
    """Regression test for the display/enforcement mismatch: submit_constraint's
    cap check must use the same period-clipped `used_days` that `remaining_days`
    (and thus the UI) reports, not a full-future-span sum.

    Sets up an approved constraint entirely inside the NEXT reset period (10
    days). Under the old `_future_cap_used` helper (no period clipping, counts
    any row with end_date >= today), that constraint alone would count as 10
    "used" days against the CURRENT period's cap — even though it doesn't
    overlap the current period at all. A subsequent 12-day request entirely
    within the current period would then be wrongly rejected (10 + 12 = 22 >
    cap 15), even though `remaining_days` would report the full cap as
    available. The fixed enforcement must accept it.
    """
    s = create_soldier(admin_session, personal_number=_pn(13))
    today = date.today()
    period_start, period_end = constraints.period_bounds("quarter", today)

    future_only = PersonalConstraint(
        soldier_id=s.id,
        start_date=period_end,
        end_date=period_end + timedelta(days=9),
        reason="next period only",
        status="approved",
    )
    admin_session.add(future_only)
    admin_session.flush()

    # The display (remaining_days) must show the current period as untouched.
    rd = constraints.remaining_days(admin_session, soldier_id=s.id)
    assert rd["used_days"] == 0
    assert rd["remaining_days"] == rd["cap_days"]

    # Enforcement must agree with the display: a 12-day request inside the
    # current period should be accepted, not rejected as cap-exceeded.
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=today + timedelta(days=1),
        end_date=today + timedelta(days=12),
        reason="within current period",
        actor_id=None,
    )
    admin_session.commit()
    assert c.status == "pending_commander"


def test_submit_cap_checked_against_requests_own_quarter_not_submission_day(admin_session):
    """Regression test: submit_constraint's cap check must anchor the period
    on the REQUEST's own start_date, not on the real submission-day `today`.
    Before the fix, a request submitted today for dates in a distant future
    quarter had zero overlap with "today's" quarter, so the cap check always
    computed requested_in_period=0 and passed regardless of how many days
    were requested — the two submissions below (10 + 10 = 20 days, cap 15)
    would both have succeeded under the old code.
    """
    s = create_soldier(admin_session, personal_number=_pn(21))
    far_anchor = date.today() + timedelta(days=200)
    period_start, _period_end = constraints.period_bounds("quarter", far_anchor)

    first_start = period_start + timedelta(days=1)
    first_end = first_start + timedelta(days=9)  # 10 days
    submit_constraint(
        admin_session, soldier_id=s.id,
        start_date=first_start, end_date=first_end, reason="a", actor_id=None,
    )
    admin_session.commit()

    second_start = first_end + timedelta(days=1)
    second_end = second_start + timedelta(days=9)  # another 10 days, same quarter
    with pytest.raises(ConstraintError, match="cap_exceeded"):
        submit_constraint(
            admin_session, soldier_id=s.id,
            start_date=second_start, end_date=second_end, reason="b", actor_id=None,
        )


def test_submit_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(4))
    with pytest.raises(ConstraintError, match="bad_date_range"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 5),
            reason="no",
            actor_id=None,
        )


def test_submit_past_start(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(5))
    with pytest.raises(ConstraintError, match="start_date_in_past"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 5),
            reason="past",
            actor_id=None,
        )


def test_submit_unknown_soldier(admin_session):
    with pytest.raises(ConstraintError, match="soldier_not_found"):
        submit_constraint(
            admin_session,
            soldier_id=uuid.uuid4(),
            start_date=date.today() + timedelta(days=1),
            end_date=date.today() + timedelta(days=5),
            reason="no",
            actor_id=None,
        )


def test_approve_pending(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(6))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    after_commander = approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    assert after_commander.status == "pending_duty_manager"
    assert after_commander.commander_approved_by == s.id
    approved = approve_constraint(
        admin_session, constraint_id=c.id, actor_id=s.id, actor_role="admin"
    )
    admin_session.commit()
    assert approved.status == "approved"
    assert approved.decided_by == s.id


def test_approve_duty_manager_step_rejects_commander(admin_session):
    """A commander may clear the commander step, but the duty-manager step
    must be reserved for duty managers and admins."""
    s = create_soldier(admin_session, personal_number=_pn(30))
    cmd = create_soldier(admin_session, personal_number=_pn(31), role="commander")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    after_commander = approve_constraint(admin_session, constraint_id=c.id, actor_id=cmd.id)
    assert after_commander.status == "pending_duty_manager"
    with pytest.raises(ConstraintError, match="not_duty_manager"):
        approve_constraint(admin_session, constraint_id=c.id, actor_id=cmd.id)


def test_approve_blocked_when_enrollment_not_approved(admin_session):
    node = create_node(admin_session, level="unit", name=f"unit_{_pn(20)}")
    s = create_soldier(admin_session, personal_number=_pn(20))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id))
    admin_session.flush()
    with pytest.raises(ConstraintError, match="enrollment_not_approved"):
        approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_approve_not_pending(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(7))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id, actor_role="admin")
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_reject(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(8))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    rejected = reject_constraint(admin_session, constraint_id=c.id, actor_id=s.id, decision_note="לא מתאים")
    admin_session.commit()
    assert rejected.status == "rejected"
    assert rejected.decision_note == "לא מתאים"


def test_cancel_pending(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(9))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None


def test_cancel_once_fully_approved_requires_a_reason(admin_session):
    # Approved constraints ARE cancelable (unlike rejected/already-cancelled
    # ones, see test_cancel_not_pending_once_rejected below) but only with an
    # explicit reason — this is the privileged/extreme-action cancellation
    # path, not the plain pre-decision withdrawal that test_cancel_pending
    # covers.
    s = create_soldier(admin_session, personal_number="7400010")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)  # -> pending_duty_manager
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id, actor_role="admin")  # -> approved
    admin_session.flush()
    with pytest.raises(ConstraintError, match="cancellation_reason_required"):
        cancel_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_cancel_not_pending_once_rejected(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(13))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    reject_constraint(admin_session, constraint_id=c.id, actor_id=s.id, decision_note="לא מתאים")
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        cancel_constraint(admin_session, constraint_id=c.id, actor_id=s.id, reason="סיבה")


def test_cancel_at_pending_duty_manager_succeeds_regardless_of_commander_actor_id(admin_session):
    # Regression test: _approve_commander_step sets c.commander_approved_by =
    # actor_id, which can be None (actor_id is an optional kwarg on
    # approve_constraint). cancel_constraint's eligibility must be based
    # purely on `status`, not on commander_approved_by being set — a
    # commander-step approval performed with actor_id=None must not change
    # whether the now-pending_duty_manager request can still be cancelled.
    s = create_soldier(admin_session, personal_number=_pn(12))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    assert c.status == "pending_commander"
    approved = approve_constraint(admin_session, constraint_id=c.id, actor_id=None)
    admin_session.flush()
    assert approved.status == "pending_duty_manager"
    assert approved.commander_approved_by is None
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None


def test_cancel_during_pending_duty_manager_succeeds(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(22))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None


def test_list_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="7400011")
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
        reason="א",
        actor_id=None,
    )
    admin_session.flush()
    assert len(list_constraints(admin_session, soldier_id=s.id)) == 1


def test_get_approved_dates(admin_session):
    s = create_soldier(admin_session, personal_number="7400012")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=10),
        end_date=date.today() + timedelta(days=15),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id, actor_role="admin")
    admin_session.flush()
    dates = get_approved_constraint_dates(admin_session, soldier_id=s.id)
    assert len(dates) == 1
    assert dates[0][0] == date.today() + timedelta(days=10)


def test_constraint_not_found(admin_session):
    with pytest.raises(ConstraintError, match="constraint_not_found"):
        approve_constraint(admin_session, constraint_id=uuid.uuid4(), actor_id=None)


def test_period_bounds_quarter():
    assert constraints.period_bounds("quarter", date(2026, 8, 15)) == (date(2026, 7, 1), date(2026, 10, 1))


def test_period_bounds_half_year():
    assert constraints.period_bounds("half_year", date(2026, 8, 15)) == (date(2026, 7, 1), date(2027, 1, 1))


def test_period_bounds_year():
    assert constraints.period_bounds("year", date(2026, 8, 15)) == (date(2026, 1, 1), date(2027, 1, 1))


def test_period_bounds_quarter_first_month():
    assert constraints.period_bounds("quarter", date(2026, 1, 15)) == (date(2026, 1, 1), date(2026, 4, 1))


def test_period_bounds_half_year_first_half():
    assert constraints.period_bounds("half_year", date(2026, 3, 1)) == (date(2026, 1, 1), date(2026, 7, 1))


def test_remaining_days_counts_only_current_period(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(10))
    # a constraint entirely inside a past quarter (relative to today=2026-08-01) must not count
    past = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 10),
        reason="x",
        status="approved",
    )
    admin_session.add(past)
    admin_session.flush()

    result = constraints.remaining_days(admin_session, soldier_id=s.id, today=date(2026, 8, 1))
    assert result["used_days"] == 0
    assert result["remaining_days"] == result["cap_days"]
    assert result["period_start"] == date(2026, 7, 1)
    assert result["period_end"] == date(2026, 10, 1)


def test_remaining_days_counts_current_period_overlap(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(11))
    # partially overlaps the start of the current quarter (2026-07-01 .. 2026-10-01)
    overlapping = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 6, 28),
        end_date=date(2026, 7, 3),
        reason="x",
        status="pending_commander",
    )
    admin_session.add(overlapping)
    admin_session.flush()

    result = constraints.remaining_days(admin_session, soldier_id=s.id, today=date(2026, 8, 1))
    # only 2026-07-01..2026-07-03 (3 days) falls within the current period
    assert result["used_days"] == 3
    assert result["remaining_days"] == result["cap_days"] - 3


def test_remaining_days_ignores_rejected(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(12))
    rejected = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 7, 5),
        end_date=date(2026, 7, 10),
        reason="x",
        status="rejected",
    )
    admin_session.add(rejected)
    admin_session.flush()

    result = constraints.remaining_days(admin_session, soldier_id=s.id, today=date(2026, 8, 1))
    assert result["used_days"] == 0

