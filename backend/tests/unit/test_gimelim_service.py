# backend/tests/unit/test_gimelim_service.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import (
    DutyAssignment,
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
    result = _passes_density(existing, date(2026, 6, 7), date(2026, 6, 7), T=7, W=14)
    assert result is True


def test_passes_density_exceeds_cap():
    """More than T days in window → fails."""
    existing = {date(2026, 6, 1) + timedelta(days=i) for i in range(7)}  # 7 days
    # Adding 1 more day → 8 total; T=7 → fails
    result = _passes_density(existing, date(2026, 6, 8), date(2026, 6, 8), T=7, W=14)
    assert result is False


# ── Preview tests ─────────────────────────────────────────────────────────────

def test_preview_raises_if_no_reserve_linked(admin_session):
    dt, loc = _seed_base(admin_session)
    actor = _make_soldier(admin_session, "act01", "Actor")
    soldier_a = _make_soldier(admin_session, "gim01", "A")
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 10), end_date=date(2026, 6, 12),
                      required_count=1)
    admin_session.add(shift)
    admin_session.flush()
    primary = DutyAssignment(
        soldier_id=soldier_a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 12),
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
        start=date(2026, 6, 10), end=date(2026, 6, 12),
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
        start=date(2026, 6, 10), end=date(2026, 6, 12),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )

    # Future shift with C as primary and D as reserve
    future_shift, c_primary, d_reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 20), end=date(2026, 6, 22),
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

    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 10), end=date(2026, 6, 12),
        primary_soldier=soldier_a, reserve_soldier=soldier_b,
    )
    future_shift, c_primary, d_reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc,
        start=date(2026, 6, 20), end=date(2026, 6, 22),
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

    # Verify reserve B was called up
    admin_session.refresh(reserve)
    assert reserve.called_up_from == date(2026, 6, 10)

    # Verify token is consumed (second commit should fail)
    with pytest.raises(GimelimError, match="token_not_found"):
        commit_gimelim(
            admin_session,
            shift_id=shift.id,
            preview_token=preview.preview_token,
            actor_id=actor.id,
        )
