"""Shared builders for requests-page response metadata.

The soldier-facing "my requests" views annotate every request row with four
derived fields: requested_at / updated_at timestamps, a waiting_on reference
(the person the row currently sits with while pending) and decided_by /
commander_approved_by person references carrying server-side resolved names.

Resolution deliberately reuses the same approval_scope helpers the approval
routing itself uses (nearest commander / duty manager chains), so what the
requests page shows as "waiting on" matches who would actually be notified to
act on the row.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Notification, NotificationType, Soldier
from app.services.approval_scope import (
    nearest_commander_for_soldier,
    nearest_duty_manager_for_soldier,
)

# PersonalConstraint statuses whose next actor is well defined.
_COMMANDER_STEP_STATUS = "pending_commander"
_DUTY_MANAGER_STEP_STATUS = "pending_duty_manager"


def soldier_names(session: Session, soldier_ids) -> dict[uuid.UUID, str]:
    """Batched id → full_name lookup; None/missing ids are skipped."""
    ids = {sid for sid in soldier_ids if sid is not None}
    if not ids:
        return {}
    rows = session.execute(select(Soldier.id, Soldier.full_name).where(Soldier.id.in_(ids))).all()
    return {sid: name for sid, name in rows}


def person_ref(
    session: Session, soldier_id: uuid.UUID | None, names: dict[uuid.UUID, str] | None = None
) -> dict[str, object] | None:
    """{"soldier_id": …, "name": …} for one soldier, or None when unset/unknown."""
    if soldier_id is None:
        return None
    if names is None or soldier_id not in names:
        names = soldier_names(session, {soldier_id})
    name = names.get(soldier_id)
    if name is None:
        return None
    return {"soldier_id": soldier_id, "name": name}


def waiting_on(
    session: Session, *, soldier_id: uuid.UUID, status: str
) -> dict[str, object] | None:
    """Who the row currently sits with, while it rests at a named pending step.

    pending_commander → the soldier's nearest commander; pending_duty_manager →
    the nearest duty manager scoped over the soldier's node — the exact people
    approval routing notifies at each step. Any other status (decided,
    cancelled, or a plain "pending" flow without named steps) → None.
    """
    if status == _COMMANDER_STEP_STATUS:
        approver_id = nearest_commander_for_soldier(session, soldier_id)
        kind = "commander"
    elif status == _DUTY_MANAGER_STEP_STATUS:
        approver_id = nearest_duty_manager_for_soldier(session, soldier_id)
        kind = "duty_manager"
    else:
        return None
    if approver_id is None:
        return None
    name = soldier_names(session, {approver_id}).get(approver_id, "")
    return {"kind": kind, "soldier_id": approver_id, "name": name}


def latest_activity(*moments: datetime | None) -> datetime | None:
    """max() over nullable, tz-aware datetimes (None entries ignored)."""
    present = [m for m in moments if m is not None]
    return max(present) if present else None


def constraint_audit_latest(session: Session, constraint_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """Latest audit-log timestamp per personal_constraint (submit / commander
    step / final decision all write audit rows) — feeds updated_at."""
    if not constraint_ids:
        return {}
    rows = session.execute(
        select(AuditLog.entity_id, func.max(AuditLog.created_at))
        .where(
            AuditLog.entity_type == "personal_constraint",
            AuditLog.entity_id.in_(constraint_ids),
        )
        .group_by(AuditLog.entity_id)
    ).all()
    return {entity_id: ts for entity_id, ts in rows}


def exemption_decision_latest(session: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """ExemptionRequest has no decided_at column; its decision instant is the
    approval/rejection notification written to the requester (same derivation
    the unseen-decision counter uses)."""
    if not request_ids:
        return {}
    rows = session.execute(
        select(Notification.reference_id, func.max(Notification.created_at))
        .where(
            Notification.reference_type == "exemption_request",
            Notification.reference_id.in_(request_ids),
            Notification.type.in_((
                NotificationType.exemption_approved,
                NotificationType.exemption_rejected,
            )),
        )
        .group_by(Notification.reference_id)
    ).all()
    return {entity_id: ts for entity_id, ts in rows}
