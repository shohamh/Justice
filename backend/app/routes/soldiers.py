from __future__ import annotations

import uuid
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed, require_roles
from app.db.models import HierarchyNode, Soldier, SoldierFieldUpdate
from app.db.session import get_session
from app.services import soldiers as svc
from app.services.soldiers import (
    approve_field_update,
    reject_field_update,
    submit_field_update,
    update_soldier_profile,
)
from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS

router = APIRouter(prefix="/soldiers", tags=["soldiers"])


class SoldierOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    phone: str | None
    must_change_password: bool
    left_at: str | None
    # Profile fields
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None


class OnboardRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=200)
    hierarchy_node_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=40)
    password: str | None = Field(default=None, max_length=200)


class OnboardResponse(SoldierOut):
    temp_password: str | None


class UpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    hierarchy_node_id: uuid.UUID | None = None


class RoleRequest(BaseModel):
    role: str = Field(pattern="^(soldier|commander|duty_manager|admin)$")


class UpdateProfileRequest(BaseModel):
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool | None = None
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None


class FieldUpdateRequest(BaseModel):
    field_name: str
    new_value: str


class FieldUpdateDecisionRequest(BaseModel):
    decision_note: str | None = None


class FieldUpdateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    field_name: str
    previous_value: str | None
    new_value: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: Any
    decision_note: str | None
    created_at: Any


def _can_see_gender(session: Session, user: Soldier, target: Soldier) -> bool:
    """Gender is visible to self, commanders in chain, DMs, admins."""
    if user.id == target.id:
        return True
    if user.role == "admin":
        return True
    if user.role in ("duty_manager", "commander"):
        from app.auth.authz import can, scope_root_ids
        roots = scope_root_ids(session, user)
        node = _node_of(session, target)
        return can(user, Action.SOLDIER_READ, target_node=node, roots=roots)
    return False


def _out(s: Soldier, *, include_gender: bool = False) -> SoldierOut:
    return SoldierOut(
        id=s.id,
        personal_number=s.personal_number,
        full_name=s.full_name,
        role=s.role,
        hierarchy_node_id=s.hierarchy_node_id,
        phone=s.phone,
        must_change_password=s.must_change_password,
        left_at=s.left_at.isoformat() if s.left_at else None,
        gender=s.gender if include_gender else None,
        is_officer=s.is_officer,
        rank=s.rank,
        bahad1_graduate=s.bahad1_graduate,
        enlistment_date=s.enlistment_date,
        mandatory_end_date=s.mandatory_end_date,
        discharge_date=s.discharge_date,
        last_mitvahim_date=s.last_mitvahim_date,
        last_alal_date=s.last_alal_date,
    )


def _fu_out(u: SoldierFieldUpdate) -> FieldUpdateOut:
    return FieldUpdateOut(
        id=u.id,
        soldier_id=u.soldier_id,
        field_name=u.field_name,
        previous_value=u.previous_value,
        new_value=u.new_value,
        status=u.status,
        decided_by=u.decided_by,
        decided_at=u.decided_at,
        decision_note=u.decision_note,
        created_at=u.created_at,
    )


def _load(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.post("", response_model=OnboardResponse, status_code=status.HTTP_201_CREATED)
def onboard(
    body: OnboardRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> OnboardResponse:
    target_node = (
        session.get(HierarchyNode, body.hierarchy_node_id) if body.hierarchy_node_id else None
    )
    authorize(session, user, Action.SOLDIER_CREATE, target_node=target_node)
    try:
        result = svc.onboard_soldier(
            session,
            personal_number=body.personal_number,
            full_name=body.full_name,
            hierarchy_node_id=body.hierarchy_node_id,
            phone=body.phone,
            password=body.password,
            actor_id=user.id,
        )
    except svc.PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short"
        ) from exc
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(result.soldier)
    return OnboardResponse(**_out(result.soldier).model_dump(), temp_password=result.temp_password)


@router.get("", response_model=list[SoldierOut])
def list_soldiers(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[SoldierOut]:
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        return [_out(s) for s in rows]
    roots = scope_root_ids(session, user)
    if not roots:
        return [_out(user)]
    rows = session.execute(select(Soldier)).scalars().all()
    out: list[SoldierOut] = []
    for s in rows:
        node = _node_of(session, s)
        if node is not None and any(r in node.path_ids for r in roots):
            out.append(_out(s))
    return out


# NOTE: /ranks and /field-updates/pending MUST come before /{soldier_id} routes
@router.get("/ranks")
def get_ranks() -> dict[str, list[str]]:
    return {"enlisted": ENLISTED_RANKS, "officers": OFFICER_RANKS}


@router.get("/field-updates/pending", response_model=list[FieldUpdateOut])
def list_all_pending_field_updates(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    """Returns pending field updates for soldiers in the caller's scope."""
    if user.role == "admin":
        rows = session.execute(
            select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
        ).scalars().all()
        return [_fu_out(r) for r in rows]
    roots = scope_root_ids(session, user)
    if not roots:
        return []
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
    ).scalars().all()
    result = []
    for upd in all_pending:
        s = session.get(Soldier, upd.soldier_id)
        if s:
            node = _node_of(session, s)
            from app.auth.authz import can
            if can(user, Action.SOLDIER_READ, target_node=node, roots=roots):
                result.append(_fu_out(upd))
    return result


@router.get("/field-updates/pending/count")
def count_pending_field_updates(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    if user.role == "admin":
        rows = session.execute(
            select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
        ).scalars().all()
        return {"count": len(rows)}
    roots = scope_root_ids(session, user)
    if not roots:
        return {"count": 0}
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
    ).scalars().all()
    total = 0
    for upd in all_pending:
        s = session.get(Soldier, upd.soldier_id)
        if s:
            node = _node_of(session, s)
            from app.auth.authz import can
            if can(user, Action.SOLDIER_READ, target_node=node, roots=roots):
                total += 1
    return {"count": total}


@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    return _out(s, include_gender=_can_see_gender(session, user, s))


@router.patch("/{soldier_id}", response_model=SoldierOut)
def update(
    soldier_id: uuid.UUID,
    body: UpdateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    svc.update_soldier(
        session, soldier=s, full_name=body.full_name, phone=body.phone,
        hierarchy_node_id=body.hierarchy_node_id, actor_id=user.id
    )
    session.commit()
    session.refresh(s)
    return _out(s)


@router.patch("/{soldier_id}/profile", response_model=SoldierOut)
def update_profile(
    soldier_id: uuid.UUID,
    body: UpdateProfileRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    update_soldier_profile(session, soldier=s, fields=fields, actor_id=user.id)
    session.commit()
    session.refresh(s)
    return _out(s, include_gender=_can_see_gender(session, user, s))


@router.post("/{soldier_id}/field-updates", response_model=FieldUpdateOut, status_code=201)
def create_field_update(
    soldier_id: uuid.UUID,
    body: FieldUpdateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    if s.id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        req = submit_field_update(
            session, soldier_id=soldier_id, field_name=body.field_name,
            new_value=body.new_value, actor_id=user.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(req)
    return _fu_out(req)


@router.get("/{soldier_id}/field-updates", response_model=list[FieldUpdateOut])
def list_field_updates(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    s = _load(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    rows = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.soldier_id == soldier_id)
        .order_by(SoldierFieldUpdate.created_at.desc())
    ).scalars().all()
    return [_fu_out(r) for r in rows]


@router.post("/{soldier_id}/field-updates/{update_id}/approve", response_model=FieldUpdateOut)
def approve_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        approve_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    return _fu_out(upd)


@router.post("/{soldier_id}/field-updates/{update_id}/reject", response_model=FieldUpdateOut)
def reject_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        reject_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    return _fu_out(upd)


@router.post("/{soldier_id}/reset-password")
def reset_password(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_RESET_PASSWORD, target_node=_node_of(session, s))
    temp = svc.reset_password(session, soldier=s, actor_id=user.id)
    session.commit()
    return {"temp_password": temp}


@router.delete("/{soldier_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_DELETE, target_node=_node_of(session, s))
    svc.soft_delete(session, soldier=s, actor_id=user.id)
    session.commit()


@router.post("/{soldier_id}/role", response_model=SoldierOut)
def set_role(
    soldier_id: uuid.UUID,
    body: RoleRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> SoldierOut:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    s = _load(session, soldier_id)
    try:
        svc.assign_role(session, soldier=s, role=body.role, actor_id=user.id)
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(s)
    return _out(s)
