# backend/tests/unit/test_gimelim_service.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import (
    AuditLog,
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    HierarchyNode,
    Soldier,
    SystemSetting,
)
from app.services.gimelim import (
    GimelimError,
    _passes_density,
    commit_gimelim,
    preview_gimelim,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_soldier(session, personal_number: str, name: str, node_id=None) -> Soldier:
    s = Soldier(
        personal_number=personal_number,
        full_name=name,
        password_hash="x",
        role="soldier",
        enrolled_at=date(2026, 1, 1),
        must_change_password=False,
        hierarchy_node_id=node_id,
    )
    session.add(s)
    session.flush()
    return s


def _make_shift_with_primary_and_reserve(
    session, dt: DutyType, loc: DutyLocation, start: date, end: date,
    primary_soldier: Soldier, reserve_soldier: Soldier
) -> tuple[DutyShift, DutyAssignment, DutyAssignment]:
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end,
        required_count=1,
    )
    session.add(shift)
    session.flush()
    primary = DutyAssignment(
        soldier_id=primary_soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end,
        status="published",
        is_reserve=False,
        duty_shift_id=shift.id,
    )
    reserve = DutyAssignment(
        soldier_id=reserve_soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end,
        status="published",
        is_reserve=True,
        duty_shift_id=shift.id,
    )
    session.add_all([primary, reserve])
    session.flush()
    link = DutyReserveLink(
        primary_assignment_id=primary.id,
        reserve_assignment_id=reserve.id,
        hierarchy_distance=1,
    )
    session.add(link)
    session.flush()
    return shift, primary, reserve


def _seed_base(session):
    dt = DutyType(name="שמירה-gim", score_per_day=Decimal("2"))
    loc = DutyLocation(name="עמדה-gim")
    session.add_all([dt, loc])
    session.flush()
    return dt, loc


# ── Density tests ─────────────────────────────────────────────────────────────

def test_passes_density_no_existing():
    """No existing duties: always passes."""
    result = _passes_density(set(), date(2026, 6, 20), date(2026, 6, 22), T=7, W=14)
    assert result is True


def test_passes_density_exactly_at_cap():
    """Exactly T days in window is OK."""
    existing = {date(2026, 6, 1) + timedelta(days=i) for i in range(6)}  # 6 days
    # Adding 1 more day → 7 total; T=7, W=14 → OK
    result = _passes_density(existing, date(2026, 6, 7), date(2026, 6, 8), T=7, W=14)
    assert result is True


def test_passes_density_exceeds_cap():
    """More than T days in window → fails."""
    existing = {date(2026, 6, 1) + timedelta(days=i) for i in range(7)}  # 7 days
    # Adding 1 more day → 8 total; T=7 → fails
    result = _passes_density(existing, date(2026, 6, 8), date(2026, 6, 9), T=7, W=14)
    assert result is False


# ── Preview tests ─────────────────────────────────────────────────────────────

def test_preview_raises_if_no_reserve_linked(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "act01", "Actor")
    soldier_a = _make_soldier(admin_session, "gim01", "A")
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date.today() - timedelta(days=2), end_date=date.today() + timedelta(days=2),
                      required_count=1)
    admin_session.add(shift)
    admin_session.flush()
    primary = DutyAssignment(
        soldier_id=soldier_a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=2), end_date=date.today() + timedelta(days=2),
        status="published", is_reserve=False, duty_shift_id=shift.id,
    )
    admin_session.add(primary)
    admin_session.flush()

    with pytest.raises(GimelimError, match="no_reserve_linked"):
        preview_gimelim(
            admin_session,
            shift_id=shift.id,
            primary_assignment_id=primary.id,
            rest_days=7,
            reason="medical leave",
            actor_id=actor.id,
        )


def test_preview_no_future_slot_gives_warning(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "act02", "Actor2")
    soldier_a = _make_soldier(admin_session, "gim02", "A")
    soldier_b = _make_soldier(admin_session, "gim03", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date.today() - timedelta(days=2), end=date.today() + timedelta(days=2),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
    )

    assert "no_future_slot_found" in preview.warnings
    assert preview.future_assignment is None
    assert preview.preview_token is not None


def test_preview_finds_future_slot(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "act03", "Actor3")
    soldier_a = _make_soldier(admin_session, "gim04", "A")
    soldier_b = _make_soldier(admin_session, "gim05", "B")
    soldier_c = _make_soldier(admin_session, "gim06", "C")
    soldier_d = _make_soldier(admin_session, "gim07", "D")

    # Current shift
    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date.today() - timedelta(days=2), end=date.today() + timedelta(days=2),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    # Future shift with C as primary and D as reserve
    future_shift, c_primary, d_reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date.today() + timedelta(days=10), end=date.today() + timedelta(days=12),
        primary_soldier=soldier_c, reserve_soldier=soldier_d,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
    )

    assert preview.future_assignment is not None
    assert preview.future_assignment.demoted_assignment_id == c_primary.id
    assert "no_future_slot_found" not in preview.warnings


def test_preview_defaults_from_date_to_today(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd1", "ActorFD1")
    soldier_a = _make_soldier(admin_session, "gimfd1", "A")
    soldier_b = _make_soldier(admin_session, "gimfd2", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date.today() - timedelta(days=2), end=date.today() + timedelta(days=2),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
    )

    token_entry = preview.preview_token
    assert token_entry is not None
    # from_date defaults to today when not passed
    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[token_entry]
    assert payload["from_date"] == date.today().isoformat()


def test_preview_accepts_backdated_from_date(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd2", "ActorFD2")
    soldier_a = _make_soldier(admin_session, "gimfd3", "A")
    soldier_b = _make_soldier(admin_session, "gimfd4", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    backdated = date(2026, 6, 11)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
        from_date=backdated,
    )

    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    assert payload["from_date"] == backdated.isoformat()


def test_preview_accepts_from_date_equal_to_shift_start(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd5", "ActorFD5")
    soldier_a = _make_soldier(admin_session, "gimfd9b", "A")
    soldier_b = _make_soldier(admin_session, "gimfd10b", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
        from_date=date(2026, 6, 10),  # == start_date, the earliest legal value
    )

    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    assert payload["from_date"] == date(2026, 6, 10).isoformat()


def test_preview_rejects_from_date_before_shift_start(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd3", "ActorFD3")
    soldier_a = _make_soldier(admin_session, "gimfd5", "A")
    soldier_b = _make_soldier(admin_session, "gimfd6", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    with pytest.raises(GimelimError, match="date_out_of_range"):
        preview_gimelim(
            admin_session,
            shift_id=shift.id,
            primary_assignment_id=primary.id,
            rest_days=7,
            reason="medical leave",
            actor_id=actor.id,
            from_date=date(2026, 6, 9),
        )


def test_preview_rejects_from_date_on_or_after_shift_end(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd4", "ActorFD4")
    soldier_a = _make_soldier(admin_session, "gimfd7", "A")
    soldier_b = _make_soldier(admin_session, "gimfd8", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    with pytest.raises(GimelimError, match="date_out_of_range"):
        preview_gimelim(
            admin_session,
            shift_id=shift.id,
            primary_assignment_id=primary.id,
            rest_days=7,
            reason="medical leave",
            actor_id=actor.id,
            from_date=date(2026, 6, 15),  # == end_date, invalid (must be < end_date)
        )


def test_preview_earliest_date_counts_from_dismissal_not_scheduled_end(admin_session):
    dt, loc = _seed_base(admin_session)
    a = _make_soldier(admin_session, "8200001", "חייל א")
    b = _make_soldier(admin_session, "8200002", "חייל ב")
    # Shift runs 2026-07-01..2026-07-11 (10 days) — A is dismissed on day 3
    # (2026-07-03), far earlier than the scheduled end (2026-07-10).
    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc, date(2026, 7, 1), date(2026, 7, 11), a, b,
    )
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="פציעה",
        actor_id=a.id,
        from_date=date(2026, 7, 3),
    )
    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    # effective_end = 2026-07-03 08:00 (assignment's default start_time) +
    # 12h base rest = 2026-07-03 20:00, + 7 extra days = 2026-07-10 20:00,
    # which is mid-day so it rounds up to 2026-07-11.
    assert payload["rest_days"] == 7
    assert payload["earliest_date"] == "2026-07-11"


def test_preview_earliest_date_without_dismissal_still_uses_scheduled_end(admin_session):
    """Sanity check: with no early dismissal (from_date == scheduled start of
    the rest window), the calculation still lines up with the assignment's
    own end when from_date is set to end_date - 1 (the normal 'dismiss on the
    last day' case used by commit_gimelim)."""
    dt, loc = _seed_base(admin_session)
    a = _make_soldier(admin_session, "8200003", "חייל ג")
    b = _make_soldier(admin_session, "8200004", "חייל ד")
    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc, date(2026, 8, 1), date(2026, 8, 5), a, b,
    )
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=0,
        reason="פציעה",
        actor_id=a.id,
        from_date=date(2026, 8, 4),  # end_date - 1, the last scheduled day
    )
    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    # effective_end = 2026-08-04 08:00 (default start_time) + 12h = 08-04 20:00
    # -> rounds up to 08-05.
    assert payload["earliest_date"] == "2026-08-05"


# ── Commit tests ──────────────────────────────────────────────────────────────

def test_commit_raises_on_expired_token(admin_session):
    """Committing with an unknown/expired token raises GimelimError."""
    actor = _make_soldier(admin_session, "act04", "Actor4")
    with pytest.raises(GimelimError, match="token_not_found"):
        commit_gimelim(
            admin_session,
            shift_id=uuid4(),
            preview_token="nonexistent-token",
            actor_id=actor.id,
        )


def test_commit_full_flow(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "act05", "Actor5")
    soldier_a = _make_soldier(admin_session, "gim08", "A")
    soldier_b = _make_soldier(admin_session, "gim09", "B")
    soldier_c = _make_soldier(admin_session, "gim10", "C")
    soldier_d = _make_soldier(admin_session, "gim11", "D")

    shift_start = date.today() - timedelta(days=2)
    shift_end = date.today() + timedelta(days=2)
    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=shift_start, end=shift_end,
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )
    future_shift, c_primary, d_reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date.today() + timedelta(days=10), end=date.today() + timedelta(days=12),
        primary_soldier=soldier_c, reserve_soldier=soldier_d,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="כאב ראש",
        actor_id=actor.id,
    )
    assert preview.future_assignment is not None

    result = commit_gimelim(
        admin_session,
        shift_id=shift.id,
        preview_token=preview.preview_token,
        actor_id=actor.id,
    )

    assert result.dismissal_id is not None
    assert result.call_up_assignment_id == reserve.id
    assert result.future_primary_assignment_id is not None
    assert result.future_demoted_assignment_id == c_primary.id

    # Verify C is now is_reserve=True
    admin_session.refresh(c_primary)
    assert c_primary.is_reserve is True

    # Verify A's new primary assignment exists on future shift
    new_a = admin_session.get(DutyAssignment, result.future_primary_assignment_id)
    assert new_a is not None
    assert new_a.soldier_id == soldier_a.id
    assert new_a.duty_shift_id == future_shift.id
    assert new_a.is_reserve is False

    # Verify reserve B was called up (from_date defaults to today when not
    # passed to preview_gimelim)
    admin_session.refresh(reserve)
    assert reserve.called_up_from == date.today()

    # commit_gimelim itself deliberately does NOT consume the token — a
    # caller's session.commit() happens after this returns, and a failed
    # commit shouldn't burn a token the caller could otherwise retry with.
    # The token is only removed once the caller explicitly confirms the
    # commit succeeded (routes/gimelim.py does this after session.commit()).
    from app.services.gimelim import _PREVIEW_STORE, consume_preview_token
    assert preview.preview_token in _PREVIEW_STORE

    consume_preview_token(preview.preview_token)
    assert preview.preview_token not in _PREVIEW_STORE

    # Verify token is consumed (second commit should fail)
    with pytest.raises(GimelimError, match="token_not_found"):
        commit_gimelim(
            admin_session,
            shift_id=shift.id,
            preview_token=preview.preview_token,
            actor_id=actor.id,
        )


def test_commit_does_not_consume_token_on_its_own(admin_session):
    """Regression: commit_gimelim must leave the token in the store on
    success, so a failed session.commit() by the caller (e.g. a deferred DB
    constraint violation) doesn't strand the user with a burned token they
    can no longer retry with. Only consume_preview_token() (called by the
    route after a successful commit) may remove it."""
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "act12", "Actor12")
    soldier_a = _make_soldier(admin_session, "gim12", "A")
    soldier_b = _make_soldier(admin_session, "gim13", "B")

    shift_start = date.today() - timedelta(days=2)
    shift_end = date.today() + timedelta(days=2)
    shift, primary, _reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=shift_start, end=shift_end,
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="כאב ראש",
        actor_id=actor.id,
    )

    commit_gimelim(
        admin_session,
        shift_id=shift.id,
        preview_token=preview.preview_token,
        actor_id=actor.id,
    )

    from app.services.gimelim import _PREVIEW_STORE
    assert preview.preview_token in _PREVIEW_STORE, (
        "commit_gimelim must not consume the token itself — that's the caller's "
        "responsibility, only after its session.commit() actually succeeds"
    )


def test_commit_uses_backdated_from_date(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd9", "ActorFD9")
    soldier_a = _make_soldier(admin_session, "gimfd9", "A")
    soldier_b = _make_soldier(admin_session, "gimfd10", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    backdated = date(2026, 6, 11)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
        from_date=backdated,
    )

    result = commit_gimelim(
        admin_session,
        shift_id=shift.id,
        preview_token=preview.preview_token,
        actor_id=actor.id,
    )

    admin_session.refresh(reserve)
    assert reserve.called_up_from == backdated
    assert reserve.called_up_to == date(2026, 6, 14)  # shift.end_date - 1 day, unchanged

    dismissal = admin_session.get(DutyDismissal, result.dismissal_id)
    assert dismissal.dismissed_from == backdated
    assert dismissal.dismissed_to == date(2026, 6, 14)


def test_commit_audit_log_uses_backdated_from_date(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "actfd11", "ActorFD11")
    soldier_a = _make_soldier(admin_session, "gimfd11", "A")
    soldier_b = _make_soldier(admin_session, "gimfd12", "B")

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 15),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    backdated = date(2026, 6, 11)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="medical leave",
        actor_id=actor.id,
        from_date=backdated,
    )

    commit_gimelim(
        admin_session,
        shift_id=shift.id,
        preview_token=preview.preview_token,
        actor_id=actor.id,
    )

    audit_entry = admin_session.execute(
        select(AuditLog).where(
            AuditLog.action == "gimelim.call_up",
            AuditLog.entity_id == reserve.id,
        )
    ).scalar_one()
    assert audit_entry.after["called_up_from"] == backdated.isoformat()
    assert audit_entry.after["called_up_to"] == date(2026, 6, 14).isoformat()


# ── Cap warning tests ─────────────────────────────────────────────────────────

def _make_full_gimelim_scene(session):
    """Returns (dt, loc, soldier_a, soldier_b, shift, primary, reserve)."""
    node = HierarchyNode(level="division", name="unit-cap", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()

    dt = DutyType(name="שמירה-cap", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-cap")
    soldier_a = _make_soldier(session, "gcap-a", "A-cap", node_id=node.id)
    soldier_b = _make_soldier(session, "gcap-b", "B-cap", node_id=node.id)
    session.add_all([dt, loc])
    session.flush()

    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=2), end_date=date.today() + timedelta(days=4), required_count=1,
    )
    session.add(shift)
    session.flush()

    primary = DutyAssignment(
        soldier_id=soldier_a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=2), end_date=date.today() + timedelta(days=4),
        status="published", is_reserve=False, duty_shift_id=shift.id,
    )
    reserve = DutyAssignment(
        soldier_id=soldier_b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=2), end_date=date.today() + timedelta(days=4),
        status="published", is_reserve=True, duty_shift_id=shift.id,
    )
    session.add_all([primary, reserve])
    session.flush()

    link = DutyReserveLink(primary_assignment_id=primary.id, reserve_assignment_id=reserve.id)
    session.add(link)
    session.flush()
    return dt, loc, soldier_a, soldier_b, shift, primary, reserve


def test_preview_gimelim_warns_when_reserve_over_cap(admin_session):
    dt, loc, soldier_a, soldier_b, shift, primary, reserve = _make_full_gimelim_scene(admin_session)

    # Saturate B's window: give them 14 existing reserve days in the same 30-day window
    extra = DutyAssignment(
        soldier_id=soldier_b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=18),
        status="published", is_reserve=True, duty_shift_id=shift.id,
    )
    admin_session.add(extra)
    admin_session.flush()

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=0,
        reason="חופשה",
        actor_id=soldier_a.id,
    )
    cap_warnings = [w for w in preview.warnings if w.startswith("reserve_cap_exceeded:")]
    assert len(cap_warnings) == 1


def test_preview_gimelim_no_warning_when_reserve_under_cap(admin_session):
    dt, loc, soldier_a, soldier_b, shift, primary, reserve = _make_full_gimelim_scene(admin_session)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=0,
        reason="חופשה",
        actor_id=soldier_a.id,
    )
    cap_warnings = [w for w in preview.warnings if w.startswith("reserve_cap_exceeded:")]
    assert len(cap_warnings) == 0
