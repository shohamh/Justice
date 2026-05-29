from __future__ import annotations

import secrets
import string
import uuid
from datetime import date
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier

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
    actor_id: uuid.UUID | None = None,
) -> Soldier:
    before = {"full_name": soldier.full_name, "phone": soldier.phone}
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
        after={"full_name": soldier.full_name, "phone": soldier.phone},
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
