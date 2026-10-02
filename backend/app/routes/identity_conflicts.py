"""Admin-only identity conflict review (SSO / registration / HR sync ambiguity)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import IdentityConflict, IdentityConflictCandidate, Soldier
from app.db.session import get_session
from app.services.identity_resolution import (
    dismiss_identity_conflict,
    mask_email,
    resolve_identity_conflict,
)

router = APIRouter(prefix="/admin/identity-conflicts", tags=["identity-conflicts"])


class ConflictCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str | None
    personal_number: str | None
    email_masked: str | None
    matched_fields: list[str]
    active: bool


class IdentityConflictOut(BaseModel):
    id: uuid.UUID
    source: str
    status: str
    ad_username: str
    personal_number: str | None
    created_at: datetime
    resolved_at: datetime | None
    chosen_soldier_id: uuid.UUID | None
    resolution_note: str | None
    candidates: list[ConflictCandidateOut]


class IdentityConflictPageOut(BaseModel):
    items: list[IdentityConflictOut]


class ResolveBody(BaseModel):
    soldier_id: uuid.UUID


class DismissBody(BaseModel):
    reason: str = Field(max_length=500)


def _out(session: Session, conflict: IdentityConflict) -> IdentityConflictOut:
    rows = session.execute(
        select(IdentityConflictCandidate, Soldier)
        .join(Soldier, Soldier.id == IdentityConflictCandidate.soldier_id)
        .where(IdentityConflictCandidate.conflict_id == conflict.id)
        .order_by(Soldier.personal_number)
    ).all()
    return IdentityConflictOut(
        id=conflict.id,
        source=conflict.source,
        status=conflict.status,
        ad_username=conflict.ad_username,
        personal_number=conflict.personal_number,
        created_at=conflict.created_at,
        resolved_at=conflict.resolved_at,
        chosen_soldier_id=conflict.chosen_soldier_id,
        resolution_note=conflict.resolution_note,
        candidates=[
            ConflictCandidateOut(
                soldier_id=soldier.id,
                full_name=soldier.full_name,
                personal_number=soldier.personal_number,
                email_masked=mask_email(soldier.email),
                matched_fields=list(candidate.matched_fields),
                active=soldier.left_at is None,
            )
            for candidate, soldier in rows
        ],
    )


def _load(session: Session, conflict_id: uuid.UUID) -> IdentityConflict:
    conflict = session.get(IdentityConflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return conflict


def _error(exc: ValueError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT if str(exc) == "conflict_not_open" else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=str(exc))


@router.get("", response_model=IdentityConflictPageOut)
def list_identity_conflicts(
    status_filter: str = Query("open", alias="status", pattern="^(open|resolved|dismissed)$"),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> IdentityConflictPageOut:
    conflicts = session.execute(
        select(IdentityConflict)
        .where(IdentityConflict.status == status_filter)
        .order_by(IdentityConflict.created_at.desc())
    ).scalars().all()
    return IdentityConflictPageOut(items=[_out(session, c) for c in conflicts])


@router.post("/{conflict_id}/resolve", response_model=IdentityConflictOut)
def resolve_conflict(
    conflict_id: uuid.UUID,
    body: ResolveBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> IdentityConflictOut:
    conflict = _load(session, conflict_id)
    try:
        resolve_identity_conflict(
            session, conflict, chosen_soldier_id=body.soldier_id, actor_id=user.id
        )
    except ValueError as exc:
        session.rollback()
        raise _error(exc) from exc
    session.commit()
    return _out(session, conflict)


@router.post("/{conflict_id}/dismiss", response_model=IdentityConflictOut)
def dismiss_conflict(
    conflict_id: uuid.UUID,
    body: DismissBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> IdentityConflictOut:
    conflict = _load(session, conflict_id)
    try:
        dismiss_identity_conflict(session, conflict, reason=body.reason, actor_id=user.id)
    except ValueError as exc:
        session.rollback()
        raise _error(exc) from exc
    session.commit()
    return _out(session, conflict)
