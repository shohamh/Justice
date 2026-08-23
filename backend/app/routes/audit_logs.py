from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed, require_roles
from app.db.models import AuditLog, HierarchyNode, PersonalConstraint, Soldier, SoldierExemption
from app.db.session import get_session

router = APIRouter(tags=["audit-logs"])

# Exact entity_type strings written by write_audit() calls in
# app/services/exemptions.py and app/services/constraints.py. This is
# deliberately an allowlist, not a passthrough: the query params look
# generic, but this endpoint only knows how to authorize these two entity
# kinds (by resolving them back to an owning soldier and re-using that
# soldier's exemption/constraint read authorization). Accepting arbitrary
# entity_type values here would silently expose other entities' audit
# history without the matching per-type authorization check.
_ALLOWED_ENTITY_TYPES = {"soldier_exemption", "personal_constraint"}


class AuditLogEntryOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    context: dict[str, Any] | None
    created_at: datetime


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _resolve_soldier_id(
    session: Session, entity_type: str, entity_id: uuid.UUID, audit_rows: list[AuditLog]
) -> uuid.UUID | None:
    """Resolve the soldier who owns this exemption/constraint record.

    Tries the live row first. Falls back to scanning the entity's own audit
    trail for a soldier_id in an earlier before/after snapshot, because
    cancel_constraint() hard-deletes the PersonalConstraint row after
    writing its audit entries (see backend/app/services/constraints.py:278)
    — without this fallback, a canceled constraint's history would be
    unreachable, which is the exact gap item 17 reports.
    """
    if entity_type == "soldier_exemption":
        exemption = session.get(SoldierExemption, entity_id)
        if exemption is not None:
            return exemption.soldier_id
    elif entity_type == "personal_constraint":
        constraint = session.get(PersonalConstraint, entity_id)
        if constraint is not None:
            return constraint.soldier_id
    for entry in audit_rows:
        for snapshot in (entry.after, entry.before):
            raw = snapshot.get("soldier_id") if snapshot else None
            if raw:
                try:
                    return uuid.UUID(str(raw))
                except ValueError:
                    continue
    return None


@router.get("/audit-logs", response_model=list[AuditLogEntryOut])
def list_audit_logs(
    entity_type: str = Query(...),
    entity_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AuditLogEntryOut]:
    if entity_type not in _ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_entity_type")

    rows = list(
        session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.desc())
        )
        .scalars()
        .all()
    )

    soldier_id = _resolve_soldier_id(session, entity_type, entity_id, rows)
    if soldier_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    if s.id != user.id:
        action = Action.EXEMPTION_READ if entity_type == "soldier_exemption" else Action.CONSTRAINT_READ
        authorize(session, user, action, target_node=_node_of(session, s))

    actor_ids = {r.actor_id for r in rows if r.actor_id is not None}
    actor_names = (
        {
            a.id: a.full_name
            for a in session.execute(select(Soldier).where(Soldier.id.in_(actor_ids))).scalars().all()
        }
        if actor_ids
        else {}
    )
    return [
        AuditLogEntryOut(
            id=r.id,
            action=r.action,
            actor_id=r.actor_id,
            actor_name=actor_names.get(r.actor_id) if r.actor_id is not None else None,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            before=r.before,
            after=r.after,
            context=r.context,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ── Admin: filterable full audit-log table ─────────────────────────────────


class AdminAuditLogEntryOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_name: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    context: dict[str, Any] | None


class AdminAuditLogActorOut(BaseModel):
    id: uuid.UUID
    full_name: str


class AdminAuditLogFacetsOut(BaseModel):
    actions: list[str]
    entity_types: list[str]
    actors: list[AdminAuditLogActorOut]


class AdminAuditLogPageOut(BaseModel):
    items: list[AdminAuditLogEntryOut]
    total: int
    facets: AdminAuditLogFacetsOut


@router.get("/admin/audit-logs", response_model=AdminAuditLogPageOut)
def admin_list_audit_logs(
    action: str | None = Query(None, max_length=200, description="Substring of the action name"),
    entity_type: str | None = Query(None, max_length=100),
    actor_id: uuid.UUID | None = Query(None),
    created_from: date | None = Query(None),
    created_to: date | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> AdminAuditLogPageOut:
    """Filterable audit-log table for administrators, newest first."""
    conditions = []
    if action:
        conditions.append(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    if created_from:
        conditions.append(
            AuditLog.created_at >= datetime.combine(created_from, time.min, tzinfo=timezone.utc)
        )
    if created_to:
        conditions.append(
            AuditLog.created_at
            < datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )

    base = select(AuditLog).where(*conditions)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = list(
        session.execute(
            base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
        ).scalars()
    )

    actor_ids = {row.actor_id for row in rows if row.actor_id}
    actor_names: dict[uuid.UUID, str] = {}
    if actor_ids:
        actor_names = {
            s.id: s.full_name
            for s in session.execute(select(Soldier).where(Soldier.id.in_(actor_ids))).scalars()
        }

    facet_actions = [
        row[0]
        for row in session.execute(
            select(AuditLog.action).distinct().order_by(AuditLog.action)
        ).all()
    ]
    facet_entity_types = [
        row[0]
        for row in session.execute(
            select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)
        ).all()
    ]
    facet_actors = [
        AdminAuditLogActorOut(id=s.id, full_name=s.full_name)
        for s in session.execute(
            select(Soldier)
            .join(AuditLog, AuditLog.actor_id == Soldier.id)
            .distinct()
            .order_by(Soldier.full_name)
            .limit(500)
        ).scalars()
    ]

    return AdminAuditLogPageOut(
        items=[
            AdminAuditLogEntryOut(
                id=row.id,
                created_at=row.created_at,
                actor_id=row.actor_id,
                actor_name=actor_names.get(row.actor_id) if row.actor_id else None,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                before=row.before,
                after=row.after,
                context=row.context,
            )
            for row in rows
        ],
        total=total,
        facets=AdminAuditLogFacetsOut(
            actions=facet_actions,
            entity_types=facet_entity_types,
            actors=facet_actors,
        ),
    )
