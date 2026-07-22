import uuid
from datetime import date, timedelta

import pytest

from app.db.models import PersonalConstraint
from app.services.constraints import (
    ConstraintError,
    approve_constraint,
    cancel_constraint,
    get_approved_constraint_dates,
    list_constraints,
    period_bounds,
    reject_constraint,
    remaining_days,
    submit_constraint,
)
from tests.helpers import create_soldier

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
    assert c.status == "pending"
    assert c.soldier_id == s.id


def test_submit_auto_approve(admin_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.constraints._get_setting_with_default",
        lambda session, key, default: False if key == "constraints.require_manager_approval" else default,
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


def test_submit_cap_period_scoped_ignores_other_period_usage(admin_session):
    # Finding I-2: submit_constraint's cap enforcement must be scoped to the
    # reset period containing the new request, matching remaining_days(). A
    # soldier who has already claimed 15 days in a FUTURE period should not
    # have those days block a same-period-fitting request today. This test
    # fails against the old _future_cap_used() (which sums ALL future
    # pending/approved days with no period boundary) and passes once
    # submit_constraint checks only the touched period's own usage.
    s = create_soldier(admin_session, personal_number=_pn(200))
    # Claim the full cap (15 days) far enough out to land in a different
    # quarter than "today".
    far_start = date.today() + timedelta(days=200)
    far_end = far_start + timedelta(days=14)
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=far_start,
        end_date=far_end,
        reason="עתידי",
        actor_id=None,
    )
    admin_session.commit()
    # A short request anchored in the *current* period should still succeed,
    # since none of the far-future days fall in this period.
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
        reason="נוכחי",
        actor_id=None,
    )
    admin_session.commit()
    assert c.status == "pending"


def test_submit_cap_straddling_periods_checks_each_period_independently(admin_session):
    # Finding I-2 design decision: when a new request spans multiple reset
    # periods, each touched period is checked against its OWN remaining cap
    # (not a single sum across the whole span). Here the current period has
    # plenty of room, but the next period is already nearly full — the
    # request should still be rejected because of the next period alone.
    s = create_soldier(admin_session, personal_number=_pn(202))
    period_start, period_end = period_bounds("quarter", date.today())
    # Fill the *next* period with cap_days - 2 (13) days.
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=period_end,
        end_date=period_end + timedelta(days=12),
        reason="ממלא את הרבעון הבא",
        actor_id=None,
    )
    admin_session.commit()
    # New request: 1 day in the current period + 3 days into the next period.
    # Current-period usage (0 + 1 = 1) is fine; next-period usage
    # (13 existing + 3 new = 16) exceeds the 15-day cap.
    with pytest.raises(ConstraintError, match="cap_exceeded"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=period_end - timedelta(days=1),
            end_date=period_end + timedelta(days=2),
            reason="חוצה רבעונים",
            actor_id=None,
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
    approved = approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.commit()
    assert approved.status == "approved"
    assert approved.decided_by == s.id


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


def test_cancel_not_pending(admin_session):
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
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        cancel_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


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
    dates = get_approved_constraint_dates(admin_session, soldier_id=s.id)
    assert len(dates) == 1
    assert dates[0][0] == date.today() + timedelta(days=10)


def test_constraint_not_found(admin_session):
    with pytest.raises(ConstraintError, match="constraint_not_found"):
        approve_constraint(admin_session, constraint_id=uuid.uuid4(), actor_id=None)


# ── period_bounds / remaining_days (Task 5.1) ──


def test_period_bounds_quarter():
    assert period_bounds("quarter", date(2026, 8, 15)) == (date(2026, 7, 1), date(2026, 10, 1))


def test_period_bounds_half_year():
    assert period_bounds("half_year", date(2026, 8, 15)) == (date(2026, 7, 1), date(2027, 1, 1))


def test_period_bounds_year():
    assert period_bounds("year", date(2026, 8, 15)) == (date(2026, 1, 1), date(2027, 1, 1))


def test_remaining_days_counts_only_current_period(admin_session):
    # NOTE: this codebase has no freeze_time convention (confirmed via grep of
    # backend/tests), and submit_constraint() rejects start_date in the past,
    # so we use dates relative to the real date.today() instead of the brief's
    # literal 2026 dates. A constraint ~200 days out is guaranteed to fall
    # outside the current (default) quarterly reset period.
    s = create_soldier(admin_session, personal_number=_pn(101))
    start = date.today() + timedelta(days=200)
    end = start + timedelta(days=5)
    submit_constraint(
        admin_session, soldier_id=s.id, start_date=start, end_date=end, reason="x", actor_id=None
    )
    admin_session.commit()
    result = remaining_days(admin_session, soldier_id=s.id, today=date.today())
    assert result["used_days"] == 0
    assert result["remaining_days"] == result["cap_days"]


def test_remaining_days_counts_overlapping_current_period(admin_session):
    # Anchor the constraint window to the *start* of the current reset period
    # (via period_bounds) rather than to date.today() with a fixed offset. A
    # fixed offset like "today + 3..today + 5" silently breaks whenever today
    # is within ~5 days of a calendar quarter's end (Mar 31 / Jun 30 / Sep 30 /
    # Dec 31), since the window could then fall in the *next* period instead
    # of the current one. Anchoring to period_start guarantees the window
    # stays inside the period regardless of where in the quarter today falls.
    # Inserted directly via the session (rather than submit_constraint())
    # because period_start can itself be in the past relative to today once
    # the quarter is already underway, which submit_constraint()'s
    # start-date-in-past check would reject.
    s = create_soldier(admin_session, personal_number=_pn(102))
    period_start, _period_end = period_bounds("quarter", date.today())
    start = period_start + timedelta(days=2)
    end = period_start + timedelta(days=4)
    c = PersonalConstraint(
        soldier_id=s.id,
        start_date=start,
        end_date=end,
        reason="x",
        status="approved",
    )
    admin_session.add(c)
    admin_session.commit()
    result = remaining_days(admin_session, soldier_id=s.id, today=date.today())
    assert result["used_days"] == 3
    assert result["remaining_days"] == result["cap_days"] - 3


def test_remaining_days_clips_constraint_straddling_period_start(admin_session):
    # Exercise the min/max clamping in remaining_days(): a constraint that
    # starts before period_start but ends inside the period should only have
    # the in-period portion (period_start..end_date) counted, not its full
    # span. submit_constraint() rejects past start dates, so the row is
    # inserted directly via the session to bypass that validation.
    s = create_soldier(admin_session, personal_number=_pn(103))
    period_start, _period_end = period_bounds("quarter", date.today())
    start = period_start - timedelta(days=10)
    end = period_start + timedelta(days=2)
    c = PersonalConstraint(
        soldier_id=s.id,
        start_date=start,
        end_date=end,
        reason="straddles period boundary",
        status="approved",
    )
    admin_session.add(c)
    admin_session.commit()
    result = remaining_days(admin_session, soldier_id=s.id, today=date.today())
    expected_used = (end - period_start).days + 1
    assert result["used_days"] == expected_used
    assert result["remaining_days"] == result["cap_days"] - expected_used

