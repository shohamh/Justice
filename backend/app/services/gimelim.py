from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.reserve import _hierarchy_distance
from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    NotificationType,
    Soldier,
)
from app.services.algorithm_bridge import build_hierarchy_maps
from app.services.eligibility import DutyTypeRequirements, _is_eligible
from app.services.notifications import create_notification
from app.services.reserves import ReserveError, call_up_reserve, check_reserve_cap, dismiss_primary
from app.services.scoring import duty_score_by_soldier
from app.services.settings_loader import SettingNotFound, get_setting


# ── In-process preview token store ──────────────────────────────────────────
# Maps token (str UUID) → (expires_at, preview_payload dict)
_PREVIEW_STORE: dict[str, tuple[datetime, dict[str, Any]]] = {}
_TOKEN_TTL_SECONDS = 300  # 5 minutes


class GimelimError(Exception):
    """Raised for invalid gimelim operations."""


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SoldierRef:
    id: uuid.UUID
    name: str
    rank: str | None


@dataclass
class ShiftRef:
    shift_id: uuid.UUID
    duty_type_name: str
    duty_location_name: str
    start_date: date
    end_date: date


@dataclass
class FutureAssignmentPreview:
    shift: ShiftRef
    soldier_demoted: SoldierRef
    demoted_assignment_id: uuid.UUID
    c_existing_reserve_assignment_id: uuid.UUID | None
    c_existing_reserve_soldier: SoldierRef | None


@dataclass
class GimelimPreview:
    preview_token: str
    preview_token_expires_at: datetime
    current_shift: ShiftRef
    soldier_a: SoldierRef
    primary_assignment_id: uuid.UUID
    reserve_assignment_id: uuid.UUID          # B's assignment id
    reserve_soldier: SoldierRef               # B
    future_assignment: FutureAssignmentPreview | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class GimelimCommitResult:
    dismissal_id: uuid.UUID
    call_up_assignment_id: uuid.UUID
    future_primary_assignment_id: uuid.UUID | None
    future_demoted_assignment_id: uuid.UUID | None
    notifications_queued: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_setting_int(session: Session, key: str, default: int) -> int:
    try:
        return int(get_setting(session, key))
    except SettingNotFound:
        return default


def _get_setting_str(session: Session, key: str, default: str) -> str:
    try:
        v = get_setting(session, key)
        return str(v) if v is not None else default
    except SettingNotFound:
        return default


def _soldier_ref(session: Session, soldier_id: uuid.UUID) -> SoldierRef:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise GimelimError(f"soldier_not_found:{soldier_id}")
    return SoldierRef(id=s.id, name=s.full_name, rank=s.rank)


def _shift_ref(session: Session, shift: DutyShift) -> ShiftRef:
    dt = session.get(DutyType, shift.duty_type_id)
    loc = session.get(DutyLocation, shift.duty_location_id)
    return ShiftRef(
        shift_id=shift.id,
        duty_type_name=dt.name if dt else str(shift.duty_type_id),
        duty_location_name=loc.name if loc else str(shift.duty_location_id),
        start_date=shift.start_date,
        end_date=shift.end_date,
    )


def _existing_duty_dates(session: Session, soldier_id: uuid.UUID) -> set[date]:
    """All published duty dates for a soldier (for density check)."""
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.is_reserve.is_(False),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalars().all()
    dates: set[date] = set()
    for a in assignments:
        d = a.start_date
        while d < a.end_date:
            dates.add(d)
            d += timedelta(days=1)
    return dates


def _passes_density(
    existing_dates: set[date],
    candidate_start: date,
    candidate_end: date,
    T: int,
    W: int,
) -> bool:
    """Check that adding [candidate_start, candidate_end] doesn't exceed T days in any W-day window."""
    candidate_dates: set[date] = set()
    d = candidate_start
    while d < candidate_end:
        candidate_dates.add(d)
        d += timedelta(days=1)
    all_dates = sorted(existing_dates | candidate_dates)
    for anchor in all_dates:
        window_end = anchor + timedelta(days=W - 1)
        count = sum(1 for x in all_dates if anchor <= x <= window_end)
        if count > T:
            return False
    return True


def _passes_eligibility(
    session: Session,
    soldier: Soldier,
    duty_type: DutyType,
) -> bool:
    raw = duty_type.requirements or {}
    if not raw:
        return True
    try:
        reqs = DutyTypeRequirements.model_validate(raw)
    except Exception:
        return True
    try:
        mitvahim_months = _get_setting_int(session, "eligibility.mitvahim_months", 6)
        alal_months = _get_setting_int(session, "eligibility.alal_months", 3)
    except Exception:
        mitvahim_months, alal_months = 6, 3
    return _is_eligible(
        soldier, reqs,
        mitvahim_months=mitvahim_months,
        alal_months=alal_months,
        today=date.today(),
    )


def _find_future_slot(
    session: Session,
    *,
    soldier_a: Soldier,
    duty_type_id: uuid.UUID,
    duty_type: DutyType,
    earliest_date: date,
    T: int,
    W: int,
) -> tuple[DutyShift, DutyAssignment, DutyAssignment | None] | None:
    """
    Find the earliest future shift of the same duty_type where:
    - soldier_a is eligible
    - density check passes after adding A
    - there is at least one primary (C) that can be demoted

    Returns (future_shift, C_assignment, D_assignment_or_None) or None.
    C is chosen as: closest hierarchy distance to A; on tie, highest score_per_day.
    """
    # Hierarchy maps for distance calc
    hier_parent, _, soldier_node, _ = build_hierarchy_maps(session)
    a_node = soldier_node.get(soldier_a.id)

    # All existing duty dates for A (for density check)
    existing_dates_a = _existing_duty_dates(session, soldier_a.id)

    # Check eligibility once (doesn't depend on shift date for most rules)
    a_eligible = _passes_eligibility(session, soldier_a, duty_type)
    if not a_eligible:
        return None

    future_shifts = session.execute(
        select(DutyShift).where(
            DutyShift.duty_type_id == duty_type_id,
            DutyShift.start_date >= earliest_date,
        ).order_by(DutyShift.start_date)
    ).scalars().all()

    # Score lookup for tiebreaker — fetch once outside the loop
    scores = duty_score_by_soldier(session)

    for shift in future_shifts:
        # Density check for A on this shift
        if not _passes_density(existing_dates_a, shift.start_date, shift.end_date, T, W):
            continue

        # Find primaries on this shift
        primaries = session.execute(
            select(DutyAssignment).where(
                DutyAssignment.duty_shift_id == shift.id,
                DutyAssignment.is_reserve.is_(False),
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        ).scalars().all()

        if not primaries:
            continue

        best_c: DutyAssignment | None = None
        best_dist = 999
        best_score = Decimal("-1")

        for p in primaries:
            # Skip if p is soldier_a themselves (edge case)
            if p.soldier_id == soldier_a.id:
                continue
            c_node = soldier_node.get(p.soldier_id)
            dist = _hierarchy_distance(a_node, c_node, hier_parent) if a_node and c_node else 999
            c_score = scores.get(p.soldier_id, Decimal("0"))
            if dist < best_dist or (dist == best_dist and c_score > best_score):
                best_dist = dist
                best_score = c_score
                best_c = p

        if best_c is None:
            continue

        # Find D (best_c's current reserve)
        link = session.execute(
            select(DutyReserveLink).where(
                DutyReserveLink.primary_assignment_id == best_c.id
            )
        ).scalar_one_or_none()
        d_assignment: DutyAssignment | None = None
        if link:
            d_assignment = session.get(DutyAssignment, link.reserve_assignment_id)

        return (shift, best_c, d_assignment)

    return None


# ── Preview ───────────────────────────────────────────────────────────────────

def preview_gimelim(
    session: Session,
    *,
    shift_id: uuid.UUID,
    primary_assignment_id: uuid.UUID,
    rest_days: int,
    reason: str | None,
    actor_id: uuid.UUID,
    from_date: date | None = None,
) -> GimelimPreview:
    """Compute a gimelim proposal without writing anything."""
    # Load primary assignment
    primary_a = session.get(DutyAssignment, primary_assignment_id)
    if primary_a is None:
        raise GimelimError("primary_not_found")
    if primary_a.duty_shift_id != shift_id:
        raise GimelimError("assignment_not_in_shift")
    if primary_a.is_reserve:
        raise GimelimError("not_a_primary")

    if not reason or not reason.strip():
        raise GimelimError("reason_required")

    # Load shift
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise GimelimError("shift_not_found")

    if from_date is None:
        from_date = date.today()
    if from_date < primary_a.start_date or from_date >= primary_a.end_date:
        raise GimelimError("date_out_of_range")

    # Load reserve (B) — must be linked
    link = session.execute(
        select(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id == primary_assignment_id
        )
    ).scalar_one_or_none()
    if link is None:
        raise GimelimError("no_reserve_linked")

    reserve_b = session.get(DutyAssignment, link.reserve_assignment_id)
    if reserve_b is None:
        raise GimelimError("reserve_not_found")

    # Load duty type
    duty_type = session.get(DutyType, primary_a.duty_type_id)
    if duty_type is None:
        raise GimelimError("duty_type_not_found")

    soldier_a = session.get(Soldier, primary_a.soldier_id)
    if soldier_a is None:
        raise GimelimError("soldier_not_found")

    T = _get_setting_int(session, "algorithm.T", 7)
    W = _get_setting_int(session, "algorithm.W", 14)
    earliest_date = primary_a.end_date + timedelta(days=rest_days)

    warnings: list[str] = []

    cap_passes, cap_current, cap_max = check_reserve_cap(
        session, reserve_b.soldier_id,
        primary_a.start_date, primary_a.end_date,
    )
    if not cap_passes:
        warnings.append(f"reserve_cap_exceeded:{cap_current}/{cap_max}")

    future_result = _find_future_slot(
        session,
        soldier_a=soldier_a,
        duty_type_id=primary_a.duty_type_id,
        duty_type=duty_type,
        earliest_date=earliest_date,
        T=T,
        W=W,
    )

    future_preview: FutureAssignmentPreview | None = None
    if future_result is None:
        warnings.append("no_future_slot_found")
    else:
        future_shift, c_assignment, d_assignment = future_result
        c_soldier = session.get(Soldier, c_assignment.soldier_id)
        d_soldier = session.get(Soldier, d_assignment.soldier_id) if d_assignment else None
        future_preview = FutureAssignmentPreview(
            shift=_shift_ref(session, future_shift),
            soldier_demoted=SoldierRef(
                id=c_soldier.id, name=c_soldier.full_name, rank=c_soldier.rank
            ) if c_soldier else SoldierRef(id=c_assignment.soldier_id, name="?", rank=None),
            demoted_assignment_id=c_assignment.id,
            c_existing_reserve_assignment_id=d_assignment.id if d_assignment else None,
            c_existing_reserve_soldier=SoldierRef(
                id=d_soldier.id, name=d_soldier.full_name, rank=d_soldier.rank
            ) if d_soldier else None,
        )

    # Store token
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_TOKEN_TTL_SECONDS)

    # Snapshot of assignment IDs for race-condition check at commit time
    payload: dict[str, Any] = {
        "shift_id": str(shift_id),
        "primary_assignment_id": str(primary_assignment_id),
        "reserve_assignment_id": str(reserve_b.id),
        "primary_soldier_id": str(primary_a.soldier_id),
        "reserve_soldier_id": str(reserve_b.soldier_id),
        "primary_status_snapshot": primary_a.status,
        "reserve_status_snapshot": reserve_b.status,
        "rest_days": rest_days,
        "from_date": from_date.isoformat(),
        "reason": reason,
        "duty_type_id": str(primary_a.duty_type_id),
        "current_shift_end": primary_a.end_date.isoformat(),
        # Future slot
        "future_shift_id": str(future_result[0].id) if future_result else None,
        "future_c_assignment_id": str(future_result[1].id) if future_result else None,
        "future_c_soldier_id": str(future_result[1].soldier_id) if future_result else None,
        "future_c_status_snapshot": future_result[1].status if future_result else None,
    }
    _PREVIEW_STORE[token] = (expires_at, payload)

    # Clean up expired tokens (lazy cleanup)
    now = datetime.now(timezone.utc)
    expired = [k for k, (exp, _) in _PREVIEW_STORE.items() if exp < now]
    for k in expired:
        del _PREVIEW_STORE[k]

    b_soldier = session.get(Soldier, reserve_b.soldier_id)

    return GimelimPreview(
        preview_token=token,
        preview_token_expires_at=expires_at,
        current_shift=_shift_ref(session, shift),
        soldier_a=_soldier_ref(session, primary_a.soldier_id),
        primary_assignment_id=primary_assignment_id,
        reserve_assignment_id=reserve_b.id,
        reserve_soldier=SoldierRef(
            id=b_soldier.id, name=b_soldier.full_name, rank=b_soldier.rank
        ) if b_soldier else SoldierRef(id=reserve_b.soldier_id, name="?", rank=None),
        future_assignment=future_preview,
        warnings=warnings,
    )


# ── Scope helper for commit re-verification ───────────────────────────────────

def resolve_preview_token_assignment(preview_token: str) -> uuid.UUID | None:
    """Return the primary_assignment_id stored in a valid (non-expired) preview token.

    Returns None if the token is unknown or expired, without consuming it.
    """
    entry = _PREVIEW_STORE.get(preview_token)
    if entry is None:
        return None
    expires_at, payload = entry
    now = datetime.now(timezone.utc)
    if expires_at < now:
        return None
    raw = payload.get("primary_assignment_id")
    if not raw:
        return None
    return uuid.UUID(raw)


# ── Commit ────────────────────────────────────────────────────────────────────

def commit_gimelim(
    session: Session,
    *,
    shift_id: uuid.UUID,
    preview_token: str,
    actor_id: uuid.UUID,
) -> GimelimCommitResult:
    """Execute the gimelim atomically. Validates preview token before writing."""
    now = datetime.now(timezone.utc)

    entry = _PREVIEW_STORE.get(preview_token)
    if entry is None:
        raise GimelimError("token_not_found")
    expires_at, payload = entry
    if expires_at < now:
        del _PREVIEW_STORE[preview_token]
        raise GimelimError("token_expired")

    if str(shift_id) != payload["shift_id"]:
        raise GimelimError("token_shift_mismatch")

    primary_assignment_id = uuid.UUID(payload["primary_assignment_id"])
    reserve_assignment_id = uuid.UUID(payload["reserve_assignment_id"])

    # Race-condition check: re-read assignments and verify status/soldier unchanged
    primary_a = session.get(DutyAssignment, primary_assignment_id)
    reserve_b = session.get(DutyAssignment, reserve_assignment_id)

    if (
        primary_a is None
        or primary_a.status != payload["primary_status_snapshot"]
        or str(primary_a.soldier_id) != payload["primary_soldier_id"]
    ):
        raise GimelimError("stale_primary_changed")
    if (
        reserve_b is None
        or reserve_b.status != payload["reserve_status_snapshot"]
        or str(reserve_b.soldier_id) != payload["reserve_soldier_id"]
    ):
        raise GimelimError("stale_reserve_changed")

    rest_days: int = payload["rest_days"]
    reason: str | None = payload["reason"]
    from_date_stored = date.fromisoformat(payload["from_date"])
    notifications_queued = 0

    # ── Step 1: Dismiss primary A ──────────────────────────────────────────
    dismissal = dismiss_primary(
        session,
        assignment=primary_a,
        from_date=from_date_stored,
        to_date=primary_a.end_date - timedelta(days=1),
        reason=reason,
        actor_id=actor_id,
    )
    dismissal.is_gimelim = True
    session.flush()

    write_audit(
        session,
        actor_id=actor_id,
        action="gimelim.dismiss",
        entity_type="duty_dismissal",
        entity_id=dismissal.id,
        after={"is_gimelim": True, "reason": reason},
    )

    # ── Step 2: Call up reserve B ──────────────────────────────────────────
    call_up_last = primary_a.end_date - timedelta(days=1)
    call_up_reserve(
        session,
        assignment=reserve_b,
        from_date=from_date_stored,
        to_date=call_up_last,
        actor_id=actor_id,
    )

    write_audit(
        session,
        actor_id=actor_id,
        action="gimelim.call_up",
        entity_type="duty_assignment",
        entity_id=reserve_b.id,
        after={"called_up_from": from_date_stored.isoformat(), "called_up_to": call_up_last.isoformat()},
    )

    # Handle reserve_fate setting for B
    reserve_fate = _get_setting_str(session, "gimalim.reserve_fate", "keep")
    if reserve_fate == "release":
        # Remove the reserve link so B is no longer attached to A's slot
        old_link = session.execute(
            select(DutyReserveLink).where(
                DutyReserveLink.primary_assignment_id == primary_assignment_id
            )
        ).scalar_one_or_none()
        if old_link:
            session.delete(old_link)
            session.flush()

    # ── Step 3 & 4: Future slot — demote C, promote A ──────────────────────
    future_primary_assignment_id: uuid.UUID | None = None
    future_demoted_assignment_id: uuid.UUID | None = None

    future_c_id_str = payload.get("future_c_assignment_id")
    future_shift_id_str = payload.get("future_shift_id")

    if future_c_id_str and future_shift_id_str:
        c_assignment_id = uuid.UUID(future_c_id_str)
        future_shift_id = uuid.UUID(future_shift_id_str)

        c_assignment = session.get(DutyAssignment, c_assignment_id)
        if c_assignment is None or c_assignment.status != payload.get("future_c_status_snapshot"):
            # Future slot changed — skip reassignment, add warning to audit
            write_audit(
                session,
                actor_id=actor_id,
                action="gimelim.reassign_skipped",
                entity_type="duty_assignment",
                entity_id=c_assignment_id,
                after={"reason": "future_slot_changed_since_preview"},
            )
        else:
            future_shift = session.get(DutyShift, future_shift_id)
            if future_shift is None:
                # Shift was deleted between preview and commit — skip reassignment
                write_audit(
                    session,
                    actor_id=actor_id,
                    action="gimelim.reassign_skipped",
                    entity_type="duty_assignment",
                    entity_id=c_assignment_id,
                    after={"reason": "future_shift_deleted_since_preview"},
                )
            else:

                # Demote C to reserve
                c_assignment.is_reserve = True
                session.flush()

                write_audit(
                    session,
                    actor_id=actor_id,
                    action="gimelim.demote_to_reserve",
                    entity_type="duty_assignment",
                    entity_id=c_assignment.id,
                    before={"is_reserve": False},
                    after={"is_reserve": True, "reason": "gimelim_rollover"},
                )
                future_demoted_assignment_id = c_assignment.id

                # Promote A — create new primary assignment on future shift
                a_new = DutyAssignment(
                    soldier_id=primary_a.soldier_id,
                    duty_type_id=primary_a.duty_type_id,
                    duty_location_id=primary_a.duty_location_id,
                    start_date=future_shift.start_date,
                    end_date=future_shift.end_date,
                    start_time=future_shift.start_time,
                    end_time=future_shift.end_time,
                    status="published",
                    is_reserve=False,
                    duty_shift_id=future_shift_id,
                    created_by=actor_id,
                    notes=f"גלגול גימלים מתורנות {primary_a.start_date.isoformat()}",
                )
                session.add(a_new)
                session.flush()

                # Link C (now reserve) as reserve backing A's new primary slot
                new_reserve_link = DutyReserveLink(
                    primary_assignment_id=a_new.id,
                    reserve_assignment_id=c_assignment.id,
                    hierarchy_distance=0,  # direct demote — not from hierarchy walk
                )
                session.add(new_reserve_link)
                session.flush()

                write_audit(
                    session,
                    actor_id=actor_id,
                    action="gimelim.reassign",
                    entity_type="duty_assignment",
                    entity_id=a_new.id,
                    after={
                        "soldier_id": str(primary_a.soldier_id),
                        "shift_id": str(future_shift_id),
                        "source": "gimelim_rollover",
                    },
                )
                future_primary_assignment_id = a_new.id

                # D (C's old reserve) stays as general reserve — no change needed;
                # the DutyReserveLink pointing to C's old (now reserve) assignment remains,
                # making D a floating general reserve on that shift.

    # ── Step 5: Notifications ──────────────────────────────────────────────
    duty_type = session.get(DutyType, primary_a.duty_type_id)
    duty_type_name = duty_type.name if duty_type else "תורנות"

    # Notify B (reserve called up)
    n = create_notification(
        session,
        soldier_id=reserve_b.soldier_id,
        type=NotificationType.gimelim_reserve_called_up,
        title=f"הוקפצת לכיסוי תורנות {duty_type_name}",
        body=f"הוקפצת לכיסוי תורנות {duty_type_name} בתאריכים {primary_a.start_date} – {primary_a.end_date} בשל גימלים",
        reference_type="duty_shift",
        reference_id=shift_id,
        actor_id=actor_id,
    )
    if n:
        notifications_queued += 1

    # Notify A (dismissed, and reassigned if slot found)
    if future_primary_assignment_id:
        n = create_notification(
            session,
            soldier_id=primary_a.soldier_id,
            type=NotificationType.gimelim_reassigned,
            title=f"שוחררת גימלים — שובצת מחדש לתורנות {duty_type_name}",
            body=(
                f"שוחררת גימלים מתורנות {duty_type_name} ({primary_a.start_date} – {primary_a.end_date}). "
                f"שובצת מחדש כראשוני בתורנות {duty_type_name}."
            ),
            reference_type="duty_shift",
            reference_id=future_shift_id if future_shift_id_str else shift_id,
            actor_id=actor_id,
        )
        if n:
            notifications_queued += 1
    else:
        n = create_notification(
            session,
            soldier_id=primary_a.soldier_id,
            type=NotificationType.gimelim_dismissed,
            title=f"שוחררת גימלים מתורנות {duty_type_name}",
            body=f"שוחררת גימלים מתורנות {duty_type_name} ({primary_a.start_date} – {primary_a.end_date}).",
            reference_type="duty_shift",
            reference_id=shift_id,
            actor_id=actor_id,
        )
        if n:
            notifications_queued += 1

    # Notify C (demoted to reserve)
    if future_demoted_assignment_id and future_c_id_str:
        c_soldier_id = uuid.UUID(payload["future_c_soldier_id"])
        future_shift_obj = session.get(DutyShift, uuid.UUID(future_shift_id_str)) if future_shift_id_str else None
        shift_date_str = str(future_shift_obj.start_date) if future_shift_obj else "?"
        n = create_notification(
            session,
            soldier_id=c_soldier_id,
            type=NotificationType.gimelim_demoted_to_reserve,
            title=f"הועברת לרזרבה בתורנות {duty_type_name}",
            body=f"הועברת לרזרבה בתורנות {duty_type_name} בתאריך {shift_date_str} — חייל שוחרר גימלים ומשובץ במקומך.",
            reference_type="duty_shift",
            reference_id=uuid.UUID(future_shift_id_str) if future_shift_id_str else shift_id,
            actor_id=actor_id,
        )
        if n:
            notifications_queued += 1

    # Consume the token
    del _PREVIEW_STORE[preview_token]

    return GimelimCommitResult(
        dismissal_id=dismissal.id,
        call_up_assignment_id=reserve_b.id,
        future_primary_assignment_id=future_primary_assignment_id,
        future_demoted_assignment_id=future_demoted_assignment_id,
        notifications_queued=notifications_queued,
    )
