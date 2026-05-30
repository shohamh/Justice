from __future__ import annotations

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


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")


def generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


ROLES = {"soldier", "commander", "duty_manager", "admin"}


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
        role="soldier",  # role changes are admin-only via assign_role
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


def assign_role(
    session: Session, *, soldier: Soldier, role: str, actor_id: uuid.UUID | None = None
) -> Soldier:
    if role not in ROLES:
        raise SoldierError(f"unknown role: {role}")
    before = {"role": soldier.role}
    soldier.role = role
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.assign_role",
        entity_type="soldier",
        entity_id=soldier.id,
        before=before,
        after={"role": role},
    )
    return soldier


PROFILE_FIELDS = {
    "gender", "is_officer", "rank", "bahad1_graduate",
    "enlistment_date", "mandatory_end_date", "discharge_date",
    "last_mitvahim_date", "last_alal_date",
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
    elif field == "gender":
        soldier.gender = raw
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
