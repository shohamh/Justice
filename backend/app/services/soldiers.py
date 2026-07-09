from __future__ import annotations

import json
import re
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier, SoldierFieldUpdate

MIN_PASSWORD_LENGTH = 10


class SoldierError(Exception):
    """Raised on an invalid soldier operation."""


class PasswordPolicyError(SoldierError):
    """Raised when a password fails policy (length-over-complexity, >= 10 chars)."""


class SoldierValidationError(SoldierError):
    """Raised when a soldier's date fields fail a cross-field sanity check."""


def _check_soldier_dates(
    *,
    enlistment_date: date | None,
    discharge_date: date | None,
    mandatory_end_date: date | None,
    is_career: bool,
) -> None:
    if discharge_date is not None and enlistment_date is not None and discharge_date <= enlistment_date:
        raise SoldierValidationError("discharge_date must be after enlistment_date")
    if mandatory_end_date is not None and discharge_date is not None and mandatory_end_date > discharge_date:
        raise SoldierValidationError("mandatory_end_date must not be after discharge_date")
    if is_career and discharge_date is not None and discharge_date < date.today():
        raise SoldierValidationError("career soldier's discharge_date cannot be in the past")


def validate_soldier_dates(soldier: Soldier) -> None:
    _check_soldier_dates(
        enlistment_date=soldier.enlistment_date,
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


def generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


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
        raise SoldierError("personal_number already exists")
    if hierarchy_node_id is not None and session.get(HierarchyNode, hierarchy_node_id) is None:
        raise SoldierError("hierarchy node not found")

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
    hierarchy_node_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Soldier:
    before: dict[str, Any] = {
        "full_name": soldier.full_name,
        "phone": soldier.phone,
        "hierarchy_node_id": str(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None,
    }
    if full_name is not None:
        soldier.full_name = full_name
    if phone is not None:
        soldier.phone = phone
    if hierarchy_node_id is not None:
        if session.get(HierarchyNode, hierarchy_node_id) is None:
            raise SoldierError("hierarchy node not found")
        soldier.hierarchy_node_id = hierarchy_node_id
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
            "hierarchy_node_id": str(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None,
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


def soft_delete(
    session: Session, *, soldier: Soldier, actor_id: uuid.UUID | None = None
) -> Soldier:
    soldier.left_at = date.today()
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
    "gender", "is_officer", "rank", "bahad1_graduate",
    "enlistment_date", "mandatory_end_date", "discharge_date",
    "last_mitvahim_date", "last_alal_date", "email", "phone",
    "profile_picture_url",
}


def update_soldier_profile(
    session: Session,
    *,
    soldier: Soldier,
    fields: dict,
    actor_id: uuid.UUID | None,
) -> Soldier:
    """DM/admin direct update of profile fields."""
    for k, v in fields.items():
        if k in PROFILE_FIELDS:
            setattr(soldier, k, v)
    validate_soldier_dates(soldier)
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.profile.update",
        entity_type="soldier",
        entity_id=soldier.id,
        after={k: str(v) for k, v in fields.items() if v is not None},
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
    # Cancel any existing pending update for the same field to avoid spamming commanders
    existing = session.execute(
        select(SoldierFieldUpdate).where(
            SoldierFieldUpdate.soldier_id == soldier_id,
            SoldierFieldUpdate.field_name == field_name,
            SoldierFieldUpdate.status == "pending",
        )
    ).scalars().all()
    for old in existing:
        old.status = "cancelled"
    req = SoldierFieldUpdate(
        soldier_id=soldier_id,
        field_name=field_name,
        previous_value=_get_current_value(soldier, field_name),
        new_value=new_value,
    )
    session.add(req)
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.submit",
        entity_type="soldier_field_update",
        entity_id=None,
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
    if update.status != "pending":
        raise SoldierError("not_pending")
    soldier = session.get(Soldier, update.soldier_id)
    if soldier is None:
        raise SoldierError("soldier_not_found")
    field = update.field_name
    raw = update.new_value
    if field == "last_mitvahim_date":
        soldier.last_mitvahim_date = date.fromisoformat(raw)
    elif field == "last_alal_date":
        soldier.last_alal_date = date.fromisoformat(raw)
    elif field == "mandatory_end_date":
        soldier.mandatory_end_date = date.fromisoformat(raw)
    elif field == "discharge_date":
        soldier.discharge_date = date.fromisoformat(raw)
    elif field == "gender":
        soldier.gender = raw
    elif field == "rank":
        soldier.rank = raw
    elif field == "phone":
        soldier.phone = raw
    elif field == "military_driving_license":
        payload = json.loads(raw)
        soldier.has_military_driving_license = payload["has_license"]
        expiry = payload.get("expiry_date")
        soldier.military_driving_license_expiry = date.fromisoformat(expiry) if expiry else None
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
    if update.status != "pending":
        raise SoldierError("not_pending")
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
