from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.auth.authz import scope_root_ids
from app.db.models import HierarchyNode, Soldier, SoldierActivationCode, SoldierHrProfile
from app.services.authority import dm_scope_covers_target
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int

# Fallback default if no setting is configured; seeded key for מדור —
# get_level_rank matches HierarchyLevelType.key, not .label.
HR_ACTIVATION_MIN_LEVEL_KEY = "group"
HR_ACTIVATION_CODE_EXPIRY_DAYS_DEFAULT = 7


class ActivationCodeError(Exception):
    pass


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _hr_activation_min_commander_level(session: Session) -> str:
    try:
        value = get_setting(session, "hr_activation.min_commander_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return HR_ACTIVATION_MIN_LEVEL_KEY


def can_generate_activation_code(session: Session, *, actor: Soldier, target: Soldier) -> bool:
    if actor.role == "admin":
        return True
    if target.hierarchy_node_id is None:
        return False
    target_node = session.get(HierarchyNode, target.hierarchy_node_id)
    if target_node is None:
        return False
    required_level = _hr_activation_min_commander_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=scope_root_ids(session, actor), target_node=target_node,
        required_level_key=required_level,
    )


def generate_activation_code(
    session: Session, *, target_soldier_id: uuid.UUID, actor: Soldier,
) -> SoldierActivationCode:
    target = session.get(Soldier, target_soldier_id)
    if target is None:
        raise ActivationCodeError("soldier_not_found")
    if not can_generate_activation_code(session, actor=actor, target=target):
        raise ActivationCodeError("forbidden")

    profile = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == target.id)
    ).scalar_one_or_none()
    if profile is None:
        raise ActivationCodeError("not_hr_linked")
    if target.hr_onboarding_completed_at is not None:
        raise ActivationCodeError("already_activated")

    now = datetime.now(tz=timezone.utc)
    session.execute(
        sa_update(SoldierActivationCode)
        .where(SoldierActivationCode.soldier_id == target.id, SoldierActivationCode.used_at.is_(None))
        .values(used_at=now)
    )

    expiry_days = get_setting_int(
        session, "hr_activation.code_expiry_days", HR_ACTIVATION_CODE_EXPIRY_DAYS_DEFAULT
    )
    code = SoldierActivationCode(
        soldier_id=target.id,
        code=_generate_code(),
        expires_at=now + timedelta(days=expiry_days),
        created_by=actor.id,
    )
    session.add(code)
    session.flush()
    return code


def consume_activation_code(session: Session, *, soldier_id: uuid.UUID, code: str) -> bool:
    """Atomically consume an unexpired, unused activation code for this
    soldier. Returns True if consumed (a valid activation attempt), False
    otherwise — callers should treat False as 'not an activation code',
    not raise."""
    now = datetime.now(tz=timezone.utc)
    result = session.execute(
        sa_update(SoldierActivationCode)
        .where(
            SoldierActivationCode.soldier_id == soldier_id,
            SoldierActivationCode.code == code,
            SoldierActivationCode.used_at.is_(None),
            SoldierActivationCode.expires_at > now,
        )
        .values(used_at=now)
        .returning(SoldierActivationCode.id)
    )
    row = result.first()
    return row is not None
