from __future__ import annotations

import json
import re
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier, SoldierFieldUpdate

MIN_PASSWORD_LENGTH = 8


class SoldierError(Exception):
    """Raised on an invalid soldier operation."""


class PasswordPolicyError(SoldierError):
    """Raised when a password fails the length and complexity policy."""


class SoldierValidationError(SoldierError):
    """Raised when a soldier's date fields fail a cross-field sanity check."""


def _check_soldier_dates(
    *,
    rank: str | None = None,
    enlistment_date: date | None,
    unit_join_date: date | None = None,
    enrolled_at: date | None = None,
    discharge_date: date | None,
    mandatory_end_date: date | None,
    is_career: bool,
) -> None:
    if discharge_date is not None and enlistment_date is not None and discharge_date <= enlistment_date:
        raise SoldierValidationError("discharge_date_before_enlistment")
    if unit_join_date is not None and enlistment_date is not None and unit_join_date < enlistment_date:
        raise SoldierValidationError("unit_join_date_before_enlistment")
    if unit_join_date is not None and enrolled_at is not None and unit_join_date > enrolled_at:
        raise SoldierValidationError("unit_join_date_after_enrollment")
    if unit_join_date is not None and discharge_date is not None and unit_join_date >= discharge_date:
        raise SoldierValidationError("unit_join_date_on_or_after_discharge")
    if (
        mandatory_end_date is not None
        and enlistment_date is not None
        and mandatory_end_date < enlistment_date
    ):
        raise SoldierValidationError("mandatory_end_before_enlistment")
    if mandatory_end_date is not None and discharge_date is not None and mandatory_end_date > discharge_date:
        raise SoldierValidationError("mandatory_end_after_discharge")
    if is_career and discharge_date is not None and discharge_date < date.today():
        raise SoldierValidationError("career_discharge_in_past")
    from app.services.eligibility import CHOVAH_ONLY_RANKS
    if (
        rank in CHOVAH_ONLY_RANKS
        and mandatory_end_date is not None
        and date.today() > mandatory_end_date
        # Only a genuine inconsistency: an explicit discharge_date that is itself
        # after mandatory_end_date. A soldier with no discharge_date yet is simply
        # still serving past their originally-planned mandatory_end_date, which is
        # common and not an error.
        and discharge_date is not None
        and discharge_date > mandatory_end_date
    ):
        raise SoldierValidationError("chovah_rank_cannot_be_keva")


def validate_soldier_dates(soldier: Soldier) -> None:
    _check_soldier_dates(
        rank=soldier.rank,
        enlistment_date=soldier.enlistment_date,
        unit_join_date=soldier.unit_join_date,
        enrolled_at=soldier.enrolled_at,
        discharge_date=soldier.discharge_date,
        mandatory_end_date=soldier.mandatory_end_date,
        is_career=soldier.is_career,
    )


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Za-z]", password):
        raise PasswordPolicyError("password must contain at least one letter")
    if not re.search(r"[0-9]", password):
        raise PasswordPolicyError("password must contain at least one digit")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        raise PasswordPolicyError("password must contain at least one symbol")


def generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + string.punctuation
    # Force one character from each required class into the random password.
    chars = [secrets.choice(alphabet) for _ in range(length)]
    if not any(c.isdigit() for c in chars):
        chars[secrets.randbelow(length)] = secrets.choice(string.digits)
    if not any(c.isalpha() for c in chars):
        chars[secrets.randbelow(length)] = secrets.choice(string.ascii_letters)
    if not any(c in string.punctuation for c in chars):
        chars[secrets.randbelow(length)] = secrets.choice(string.punctuation)
    return "".join(chars)


def bump_token_version(soldier: Soldier) -> None:
    """Increment token_version to invalidate all existing refresh tokens."""
    soldier.token_version = getattr(soldier, "token_version", 1) + 1


class OnboardResult(NamedTuple):
    soldier: Soldier
    temp_password: str | None  # set only when the system generated the password


def onboard_soldier(
    session: Session,
    *,
    personal_number: str,
    full_name: str,
    hierarchy_node_id: uuid.UUID | None,
    phone: str | None = None,
    password: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> OnboardResult:
    if session.execute(
        select(Soldier.id).where(Soldier.personal_number == personal_number)
    ).first():
        raise SoldierError("personal_number_exists")
    if hierarchy_node_id is not None and session.get(HierarchyNode, hierarchy_node_id) is None:
        raise SoldierError("hierarchy_node_not_found")

    temp_password: str | None = None
    if password is None:
        password = generate_temp_password()
        temp_password = password
    validate_password(password)

    soldier = Soldier(
        personal_number=personal_number,
        full_name=full_name,
        password_hash=hash_password(password),
        role="soldier",  # role is derived/read-only; recomputed from scope data elsewhere
        hierarchy_node_id=hierarchy_node_id,
        phone=phone,
        must_change_password=True,
    )
    session.add(soldier)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.create",
        entity_type="soldier",
        entity_id=soldier.id,
        after={
            "personal_number": personal_number,
            "full_name": full_name,
            "hierarchy_node_id": str(hierarchy_node_id) if hierarchy_node_id else None,
        },
    )
    return OnboardResult(soldier=soldier, temp_password=temp_password)


def update_soldier(
    session: Session,
    *,
    soldier: Soldier,
    full_name: str | None,
    phone: str | None,
    actor_id: uuid.UUID | None = None,
) -> Soldier:
    """Update a soldier's basic profile fields.

    Deliberately does not accept hierarchy_node_id: moving a soldier between
    hierarchy nodes must go through app.services.hierarchy_transfers, which
    requires destination-side approval (Action.HIERARCHY_TRANSFER) rather than
    the broader Action.SOLDIER_UPDATE this route otherwise checks. A prior
    version let hierarchy_node_id ride along with an ordinary profile edit,
    silently moving the soldier without ever creating an approvable request.
    """
    before: dict[str, Any] = {
        "full_name": soldier.full_name,
        "phone": soldier.phone,
    }
    if full_name is not None:
        soldier.full_name = full_name
    if phone is not None:
        soldier.phone = phone
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.update",
        entity_type="soldier",
        entity_id=soldier.id,
        before=before,
        after={
            "full_name": soldier.full_name,
            "phone": soldier.phone,
        },
    )
    return soldier


def reset_password(session: Session, *, soldier: Soldier, actor_id: uuid.UUID | None = None) -> str:
    temp = generate_temp_password()
    soldier.password_hash = hash_password(temp)
    soldier.must_change_password = True
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.reset_password",
        entity_type="soldier",
        entity_id=soldier.id,
    )
    return temp


def promote_to_admin(
    session: Session,
    *,
    soldier: Soldier,
    actor_id: uuid.UUID | None,
) -> Soldier:
    """Promote a soldier to the administrator display role and audit the change.

    Password reauthentication belongs at the authenticated route boundary, so
    this service receives neither a plaintext password nor password metadata.
    """
    if soldier.role == "admin":
        return soldier
    previous_role = soldier.role
    soldier.role = "admin"
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.role.promote_admin",
        entity_type="soldier",
        entity_id=soldier.id,
        before={"role": previous_role},
        after={"role": "admin"},
    )
    return soldier


def soft_delete(
    session: Session,
    *,
    soldier: Soldier,
    actor_id: uuid.UUID | None = None,
    left_at: date | None = None,
) -> Soldier:
    soldier.left_at = left_at or date.today()
    from app.db.models import ExemptionRequest, PersonalConstraint, SwapCandidate, SwapRequest
    session.execute(
        sa_update(ExemptionRequest)
        .where(
            ExemptionRequest.soldier_id == soldier.id,
            ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
        )
        .values(status="cancelled")
    )
    session.execute(
        sa_update(PersonalConstraint)
        .where(
            PersonalConstraint.soldier_id == soldier.id,
            PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager")),
        )
        .values(status="cancelled")
    )
    # "pending_approval" no longer exists as a SwapRequest.status value — that
    # in-progress state now lives on SwapCandidate rows (see swaps.py). Only
    # "open" requests need cancelling here; their still-live candidates are
    # cancelled alongside so nothing is left pointing at a resolved request.
    cancelled_swap_ids = session.execute(
        select(SwapRequest.id).where(
            SwapRequest.requesting_soldier_id == soldier.id,
            SwapRequest.status == "open",
        )
    ).scalars().all()
    if cancelled_swap_ids:
        session.execute(
            sa_update(SwapRequest)
            .where(SwapRequest.id.in_(cancelled_swap_ids))
            .values(status="cancelled")
        )
        session.execute(
            sa_update(SwapCandidate)
            .where(
                SwapCandidate.swap_request_id.in_(cancelled_swap_ids),
                SwapCandidate.status.in_(["pending", "accepted"]),
            )
            .values(status="cancelled")
        )
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.soft_delete",
        entity_type="soldier",
        entity_id=soldier.id,
        after={"left_at": soldier.left_at.isoformat()},
    )
    return soldier


PROFILE_FIELDS = {
    "gender", "is_officer", "rank", "rank_track", "bahad1_graduate",
    "enlistment_date", "mandatory_end_date", "discharge_date",
    "last_mitvahim_date", "last_alal_date", "email", "phone",
    "profile_picture_url", "next_rank_date",
    "food_type", "food_constraints",
}

# Fields that feed rank/track compatibility (directly, or via is_career's
# derivation). A PATCH that doesn't touch any of these can't move the soldier
# into a new incompatible combination, so it shouldn't be blocked by one that
# already existed before this validation was introduced.
_RANK_TRACK_AFFECTING_FIELDS = {"rank", "rank_track", "mandatory_end_date", "discharge_date"}


def _reset_rank_advancement(session: Session, soldier: Soldier, *, since: date) -> None:
    """Re-derive next_rank_date from the rank ladder as of `since` and clear
    any manual override — used whenever a soldier's rank is set directly
    (not via an explicit next_rank_date edit)."""
    from app.services.rank_advancement import compute_initial_next_rank_date, resolve_track
    soldier.rank_track = resolve_track(soldier.rank, soldier.rank_track)
    soldier.current_rank_since = soldier.enlistment_date or since
    soldier.next_rank_date = compute_initial_next_rank_date(
        session,
        rank=soldier.rank,
        enlistment_date=soldier.enlistment_date,
        fallback_since=soldier.current_rank_since,
        track=soldier.rank_track,
    )
    soldier.next_rank_date_overridden = False


def update_soldier_profile(
    session: Session,
    *,
    soldier: Soldier,
    fields: dict,
    actor_id: uuid.UUID | None,
) -> Soldier:
    """DM/admin direct update of profile fields."""
    from app.services.eligibility import derive_is_career, validate_rank_track_compatibility
    # Snapshot the pre-update values so a PATCH that merely re-sends the
    # soldier's current rank/track (both frontend save paths always include
    # them when the actor is authorized) isn't mistaken for an actual change
    # — that would wrongly re-anchor a worker-promoted soldier's schedule
    # back to enlistment (see finding 1 of the final-review fix wave).
    old_rank = soldier.rank
    old_rank_track = soldier.rank_track
    old_enlistment_date = soldier.enlistment_date
    for k, v in fields.items():
        if k in PROFILE_FIELDS and not (k == "next_rank_date" and v is None):
            setattr(soldier, k, v)
    rank_or_track_changed = (
        ("rank" in fields and fields["rank"] != old_rank)
        or ("rank_track" in fields and fields["rank_track"] != old_rank_track)
    )
    enlistment_date_changed = (
        "enlistment_date" in fields and fields["enlistment_date"] != old_enlistment_date
    )
    if rank_or_track_changed:
        from app.services.rank_advancement import resolve_track
        requested_track = soldier.rank_track
        resolved_track = resolve_track(soldier.rank, requested_track)
        if soldier.rank is not None and requested_track is not None and resolved_track != requested_track:
            raise SoldierValidationError("rank_track_invalid")
        soldier.rank_track = resolved_track
    if rank_or_track_changed and fields.get("next_rank_date") is not None:
        soldier.current_rank_since = soldier.enlistment_date or date.today()
        soldier.next_rank_date_overridden = True
    elif rank_or_track_changed:
        _reset_rank_advancement(session, soldier, since=date.today())
    elif "next_rank_date" in fields:
        if fields["next_rank_date"] is None:
            _reset_rank_advancement(session, soldier, since=date.today())
        else:
            soldier.next_rank_date_overridden = True
    elif enlistment_date_changed and not soldier.next_rank_date_overridden:
        # Re-anchor an initial/manual (non-overridden) soldier's schedule so a
        # corrected enlistment_date typo doesn't leave current_rank_since
        # pointing at the old date — that equality is exactly what
        # compute_next_rank_date_for_soldier/recompute_affected_soldiers use
        # to tell an initial schedule apart from a system-promoted one.
        _reset_rank_advancement(session, soldier, since=date.today())
    soldier.is_career = derive_is_career(soldier.rank, soldier.mandatory_end_date, soldier.discharge_date)
    # Only validate rank/track compatibility when this PATCH actually touches
    # a field that affects it (rank itself, or a date that feeds is_career).
    # Otherwise a pre-existing (possibly grandfathered, pre-validation) bad
    # combination would permanently lock the soldier out of unrelated edits
    # like phone/email, since re-validating the whole current state on every
    # save would keep rejecting the untouched, already-broken combination.
    if _RANK_TRACK_AFFECTING_FIELDS & fields.keys():
        try:
            validate_rank_track_compatibility(soldier.rank, soldier.is_career)
        except ValueError as exc:
            raise SoldierValidationError(str(exc)) from exc
    validate_soldier_dates(soldier)
    audit_after = {k: str(v) for k, v in fields.items() if v is not None}
    if "next_rank_date" in fields and fields["next_rank_date"] is None:
        audit_after["next_rank_date"] = (
            soldier.next_rank_date.isoformat() if soldier.next_rank_date else None
        )
        audit_after["next_rank_date_overridden"] = soldier.next_rank_date_overridden
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.profile.update",
        entity_type="soldier",
        entity_id=soldier.id,
        after=audit_after,
    )
    return soldier


def _get_current_value(soldier: Soldier, field_name: str) -> str | None:
    if field_name == "military_driving_license":
        return json.dumps({
            "has_license": bool(soldier.has_military_driving_license),
            "expiry_date": soldier.military_driving_license_expiry.isoformat()
                if soldier.military_driving_license_expiry else None,
        })
    raw = getattr(soldier, field_name, None)
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw.isoformat()
    return str(raw)


def _normalize_optional_str(value) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _is_same_value(soldier: Soldier, field_name: str, new_value: str) -> bool:
    """True when the normalized requested value equals the currently stored value."""
    raw = (new_value or "").strip()
    if field_name == "rank":
        rank_value = raw
        rank_track_value: str | None = None
        has_track_component = False
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and "rank" in payload:
            rank_value = payload["rank"]
            rank_track_value = payload.get("rank_track")
            has_track_component = True
        if rank_value != soldier.rank:
            return False
        return not has_track_component or rank_track_value == soldier.rank_track
    if field_name == "military_driving_license":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        expiry = _normalize_optional_str(payload.get("expiry_date"))
        current_expiry = (
            soldier.military_driving_license_expiry.isoformat()
            if soldier.military_driving_license_expiry else None
        )
        return (
            bool(payload.get("has_license")) == bool(soldier.has_military_driving_license)
            and expiry == current_expiry
        )
    if field_name in {
        "last_mitvahim_date", "last_alal_date", "mandatory_end_date", "discharge_date", "unit_join_date",
    }:
        current = getattr(soldier, field_name, None)
        return _normalize_optional_str(raw) == (current.isoformat() if current else None)
    # Plain string fields (gender, phone, rank_track): strip both sides.
    return raw == (_normalize_optional_str(getattr(soldier, field_name, None)) or "")


def submit_field_update(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    field_name: str,
    new_value: str,
    actor_id: uuid.UUID,
) -> SoldierFieldUpdate:
    from app.services.eligibility import SOLDIER_EDITABLE_FIELDS
    if field_name not in SOLDIER_EDITABLE_FIELDS:
        raise SoldierError("field_not_editable")
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise SoldierError("soldier_not_found")
    if _is_same_value(soldier, field_name, new_value):
        raise SoldierError("same_value")
    actor = session.get(Soldier, actor_id)
    if actor is None:
        raise SoldierError("actor_not_found")
    if field_name == "unit_join_date":
        from app.services.approval_scope import (
            commander_chain_for_soldier,
            duty_manager_chain_for_soldier,
            unit_join_date_initiator_authorized,
            unit_join_date_stage_authorized,
        )
        from app.services.notifications import notify_field_update_stage
        if soldier.left_at is not None or soldier.enrolled_at is None:
            raise SoldierError("soldier_not_active")
        if not unit_join_date_initiator_authorized(session, actor=actor, target=soldier):
            raise SoldierError("forbidden")
        try:
            candidate = date.fromisoformat(new_value)
        except ValueError as exc:
            raise SoldierValidationError("unit_join_date_invalid") from exc
        _check_soldier_dates(
            rank=soldier.rank, enlistment_date=soldier.enlistment_date,
            unit_join_date=candidate, enrolled_at=soldier.enrolled_at,
            discharge_date=soldier.discharge_date, mandatory_end_date=soldier.mandatory_end_date,
            is_career=soldier.is_career,
        )
    # Cancel any existing pending update for the same field to avoid spamming commanders
    existing = session.execute(
        select(SoldierFieldUpdate).where(
            SoldierFieldUpdate.soldier_id == soldier_id,
            SoldierFieldUpdate.field_name == field_name,
            SoldierFieldUpdate.status.in_(("pending", "pending_commander", "pending_duty_manager")),
        )
    ).scalars().all()
    for old in existing:
        old.status = "superseded" if field_name == "unit_join_date" else "cancelled"
    req = SoldierFieldUpdate(
        soldier_id=soldier_id,
        field_name=field_name,
        previous_value=_get_current_value(soldier, field_name),
        new_value=new_value,
    )
    session.add(req)
    session.flush()
    if field_name == "unit_join_date":
        target_node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
        auto_commander = (
            actor.id != soldier.id
            and unit_join_date_stage_authorized(
                session, actor=actor, target_node=target_node, stage="commander"
            )
        )
        auto_duty_manager = (
            actor.id != soldier.id
            and unit_join_date_stage_authorized(
                session, actor=actor, target_node=target_node, stage="duty_manager"
            )
        )
        if auto_commander:
            req.commander_approved_by = actor.id
            req.commander_approved_at = datetime.now(tz=timezone.utc)
            write_audit(session, actor_id=actor_id, action="soldier.field_update.commander_approve", entity_type="soldier_field_update", entity_id=req.id, after={"field": field_name})
        if auto_duty_manager:
            req.duty_manager_approved_by = actor.id
            req.duty_manager_approved_at = datetime.now(tz=timezone.utc)
            write_audit(session, actor_id=actor_id, action="soldier.field_update.duty_manager_approve", entity_type="soldier_field_update", entity_id=req.id, after={"field": field_name})
        if auto_commander and auto_duty_manager:
            soldier.unit_join_date = candidate
            req.status = "approved"
            req.decided_by = actor.id
            req.decided_at = datetime.now(tz=timezone.utc)
            notify_field_update_stage(
                session, soldier_id=soldier_id, approver_id=soldier_id,
                update_id=req.id, pending=False, actor_id=actor_id,
            )
        elif auto_commander:
            req.status = "pending_duty_manager"
            dm_ids = duty_manager_chain_for_soldier(session, soldier_id)
            if dm_ids:
                notify_field_update_stage(session, soldier_id=soldier_id, approver_id=dm_ids[0], update_id=req.id, pending=True, actor_id=actor_id)
        elif auto_duty_manager:
            req.decided_by = actor.id
            req.status = "pending_commander"
            cmd_ids = commander_chain_for_soldier(session, soldier_id)
            if cmd_ids:
                notify_field_update_stage(session, soldier_id=soldier_id, approver_id=cmd_ids[0], update_id=req.id, pending=True, actor_id=actor_id)
        else:
            req.status = "pending_commander"
            cmd_ids = commander_chain_for_soldier(session, soldier_id)
            if cmd_ids:
                notify_field_update_stage(session, soldier_id=soldier_id, approver_id=cmd_ids[0], update_id=req.id, pending=True, actor_id=actor_id)
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.submit",
        entity_type="soldier_field_update",
        entity_id=req.id,
        after={"soldier_id": str(soldier_id), "field": field_name, "value": new_value},
    )
    return req


def approve_field_update(
    session: Session,
    *,
    update: SoldierFieldUpdate,
    actor_id: uuid.UUID,
    decision_note: str | None = None,
) -> SoldierFieldUpdate:
    from app.services.eligibility import derive_is_career, validate_rank_track_compatibility
    if update.status not in {"pending", "pending_commander", "pending_duty_manager"}:
        raise SoldierError("not_pending")
    soldier = session.get(Soldier, update.soldier_id)
    if soldier is None:
        raise SoldierError("soldier_not_found")
    field = update.field_name
    raw = update.new_value
    if field == "unit_join_date":
        actor = session.get(Soldier, actor_id)
        target_node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
        from app.services.approval_scope import unit_join_date_stage_authorized
        from app.services.notifications import notify_field_update_stage
        stage = "commander" if update.status == "pending_commander" else "duty_manager"
        if not actor or not unit_join_date_stage_authorized(session, actor=actor, target_node=target_node, stage=stage):
            raise SoldierError("forbidden")
        if stage == "commander" and update.duty_manager_approved_by == actor_id:
            raise SoldierError("self_approval_forbidden")
        if stage == "duty_manager" and update.commander_approved_by == actor_id:
            raise SoldierError("self_approval_forbidden")
        try:
            candidate = date.fromisoformat(raw)
        except ValueError as exc:
            raise SoldierValidationError("unit_join_date_invalid") from exc
        _check_soldier_dates(rank=soldier.rank, enlistment_date=soldier.enlistment_date, unit_join_date=candidate,
                             enrolled_at=soldier.enrolled_at, discharge_date=soldier.discharge_date,
                             mandatory_end_date=soldier.mandatory_end_date, is_career=soldier.is_career)
        if stage == "commander":
            update.commander_approved_by = actor_id
            update.commander_approved_at = datetime.now(tz=timezone.utc)
            update.commander_approval_note = decision_note
            action = "soldier.field_update.commander_approve"
            if update.duty_manager_approved_by:
                soldier.unit_join_date = candidate
                update.status = "approved"
                notify_field_update_stage(
                    session, soldier_id=soldier.id, approver_id=soldier.id,
                    update_id=update.id, pending=False, actor_id=actor_id,
                )
            else:
                update.status = "pending_duty_manager"
                from app.services.approval_scope import nearest_duty_manager_for_soldier
                dm_id = nearest_duty_manager_for_soldier(session, soldier.id)
                if dm_id:
                    notify_field_update_stage(session, soldier_id=soldier.id, approver_id=dm_id, update_id=update.id, pending=True, actor_id=actor_id)
        else:
            soldier.unit_join_date = candidate
            update.duty_manager_approved_by = actor_id
            update.duty_manager_approved_at = datetime.now(tz=timezone.utc)
            update.status = "approved"
            action = "soldier.field_update.duty_manager_approve"
            notify_field_update_stage(
                session, soldier_id=soldier.id, approver_id=soldier.id,
                update_id=update.id, pending=False, actor_id=actor_id,
            )
        update.decided_by = actor_id
        update.decided_at = datetime.now(tz=timezone.utc)
        update.decision_note = decision_note
        write_audit(session, actor_id=actor_id, action=action, entity_type="soldier_field_update", entity_id=update.id, after={"field": field, "value": raw, "status": update.status})
        return update
    if field == "last_mitvahim_date":
        soldier.last_mitvahim_date = date.fromisoformat(raw)
    elif field == "last_alal_date":
        soldier.last_alal_date = date.fromisoformat(raw)
    elif field == "unit_join_date":
        soldier.unit_join_date = date.fromisoformat(raw)
    elif field == "mandatory_end_date":
        soldier.mandatory_end_date = date.fromisoformat(raw)
    elif field == "discharge_date":
        soldier.discharge_date = date.fromisoformat(raw)
    elif field == "gender":
        soldier.gender = raw
    elif field == "rank":
        rank_value = raw
        rank_track_value: str | None = soldier.rank_track
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and "rank" in payload:
                rank_value = payload["rank"]
                rank_track_value = payload.get("rank_track")
        except json.JSONDecodeError:
            pass
        from app.services.rank_advancement import resolve_track
        resolved_track = resolve_track(rank_value, rank_track_value)
        if rank_value is not None and rank_track_value is not None and resolved_track != rank_track_value:
            raise SoldierValidationError("rank_track_invalid")
        soldier.rank = rank_value
        soldier.rank_track = resolved_track
        _reset_rank_advancement(session, soldier, since=date.today())
    elif field == "rank_track":
        from app.services.rank_advancement import resolve_track
        resolved_track = resolve_track(soldier.rank, raw)
        if soldier.rank is not None and resolved_track != raw:
            raise SoldierValidationError("rank_track_invalid")
        soldier.rank_track = raw
        _reset_rank_advancement(session, soldier, since=date.today())
    elif field == "phone":
        soldier.phone = raw
    elif field == "food_type":
        soldier.food_type = raw if raw else None
    elif field == "food_constraints":
        soldier.food_constraints = raw if raw else None
    elif field == "military_driving_license":
        payload = json.loads(raw)
        soldier.has_military_driving_license = payload["has_license"]
        expiry = payload.get("expiry_date")
        soldier.military_driving_license_expiry = date.fromisoformat(expiry) if expiry else None
    soldier.is_career = derive_is_career(soldier.rank, soldier.mandatory_end_date, soldier.discharge_date)
    try:
        validate_rank_track_compatibility(soldier.rank, soldier.is_career)
    except ValueError as exc:
        raise SoldierValidationError(str(exc)) from exc
    validate_soldier_dates(soldier)
    update.status = "approved"
    update.decided_by = actor_id
    update.decided_at = datetime.now(tz=timezone.utc)
    update.decision_note = decision_note
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.approve",
        entity_type="soldier_field_update",
        entity_id=update.id,
        after={"field": field, "value": raw},
    )
    return update


def reject_field_update(
    session: Session,
    *,
    update: SoldierFieldUpdate,
    actor_id: uuid.UUID,
    decision_note: str | None = None,
) -> SoldierFieldUpdate:
    if update.status not in {"pending", "pending_commander", "pending_duty_manager"}:
        raise SoldierError("not_pending")
    if update.field_name == "unit_join_date":
        actor = session.get(Soldier, actor_id)
        soldier = session.get(Soldier, update.soldier_id)
        target_node = (
            session.get(HierarchyNode, soldier.hierarchy_node_id)
            if soldier is not None and soldier.hierarchy_node_id else None
        )
        from app.services.approval_scope import unit_join_date_stage_authorized
        stage = "commander" if update.status == "pending_commander" else "duty_manager"
        if not actor or not unit_join_date_stage_authorized(session, actor=actor, target_node=target_node, stage=stage):
            raise SoldierError("forbidden")
        if stage == "commander" and update.duty_manager_approved_by == actor_id:
            raise SoldierError("self_approval_forbidden")
        if stage == "duty_manager" and update.commander_approved_by == actor_id:
            raise SoldierError("self_approval_forbidden")
    update.status = "rejected"
    update.decided_by = actor_id
    update.decided_at = datetime.now(tz=timezone.utc)
    update.decision_note = decision_note
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.reject",
        entity_type="soldier_field_update",
        entity_id=update.id,
    )
    return update
