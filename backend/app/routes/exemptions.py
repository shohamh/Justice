from __future__ import annotations

import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import (
    Action,
    authorize,
    can_see_private,
    can_view_medical_document,
    is_duty_manager,
)
from app.auth.deps import require_password_changed
from app.db.models import (
    ExemptionType,
    HierarchyNode,
    Soldier,
    SoldierExemption,
    SoldierExemptionFile,
)
from app.db.session import get_session
from app.rate_limit import limiter
from app.services import exemptions as svc
from app.services.file_validation import FileValidationError, validate_exemption_file

router = APIRouter(prefix="/soldiers/{soldier_id}/exemptions", tags=["exemptions"])


class ExemptionOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID | None
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by: uuid.UUID | None
    revoke_reason: str | None
    revoked_by_name: str | None
    can_cancel: bool = False


class ExemptionDetailOut(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by_name: str | None
    revoke_reason: str | None
    revoked_by_name: str | None


class GrantRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)
    is_medical: bool = False


class ExemptionFileOut(BaseModel):
    id: uuid.UUID
    file_name: str
    content_type: str
    created_at: str


def _out(session: Session, ex: SoldierExemption, include_sensitive: bool = True, can_cancel: bool = False) -> ExemptionOut:
    revoked_by_name = None
    if include_sensitive and ex.revoked_by is not None:
        revoker = session.get(Soldier, ex.revoked_by)
        revoked_by_name = revoker.full_name if revoker else None
    return ExemptionOut(
        id=ex.id,
        soldier_id=ex.soldier_id,
        exemption_type_id=ex.exemption_type_id if include_sensitive else None,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason if include_sensitive else None,
        granted_by=ex.granted_by,
        revoke_reason=ex.revoke_reason if include_sensitive else None,
        revoked_by_name=revoked_by_name,
        can_cancel=can_cancel,
    )


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_exemption(session: Session, soldier_id: uuid.UUID, exemption_id: uuid.UUID) -> tuple[Soldier, SoldierExemption]:
    soldier = _load_soldier(session, soldier_id)
    exemption = session.get(SoldierExemption, exemption_id)
    if exemption is None or exemption.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return soldier, exemption


def _authorize_file_read(
    session: Session, user: Soldier, target: Soldier, exemption: SoldierExemption
) -> None:
    if target.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, target))
    exemption_type = session.get(ExemptionType, exemption.exemption_type_id)
    if (
        (exemption.is_medical or (exemption_type is not None and exemption_type.is_medical))
        and target.id != user.id
        and not can_view_medical_document(session, user, target)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no_permission")


def _file_out(file: SoldierExemptionFile) -> ExemptionFileOut:
    return ExemptionFileOut(
        id=file.id,
        file_name=file.file_name,
        content_type=file.content_type,
        created_at=file.created_at.isoformat(),
    )


@router.get("", response_model=list[ExemptionOut])
def list_(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    include_sensitive = can_see_private(session, user, s)
    from app.services.authority import request_cancellation_authorized
    can_cancel = request_cancellation_authorized(session, user=user, target_node=_node_of(session, s))
    return [
        _out(session, ex, include_sensitive=include_sensitive, can_cancel=can_cancel)
        for ex in svc.list_exemptions(session, soldier_id=soldier_id)
    ]


@router.get("/{exemption_id}", response_model=ExemptionDetailOut)
def get_detail(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionDetailOut:
    s = _load_soldier(session, soldier_id)
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    ex_type = session.get(ExemptionType, ex.exemption_type_id) if ex.exemption_type_id else None
    include_sensitive = can_see_private(session, user, s)
    granted_by_name = None
    if ex.granted_by is not None:
        granter = session.get(Soldier, ex.granted_by)
        granted_by_name = granter.full_name if granter else None
    revoked_by_name = None
    if include_sensitive and ex.revoked_by is not None:
        revoker = session.get(Soldier, ex.revoked_by)
        revoked_by_name = revoker.full_name if revoker else None
    return ExemptionDetailOut(
        id=ex.id,
        exemption_type_name=ex_type.name if ex_type else "—",
        is_global=ex_type.is_global if ex_type else False,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason if include_sensitive else None,
        granted_by_name=granted_by_name,
        revoke_reason=ex.revoke_reason if include_sensitive else None,
        revoked_by_name=revoked_by_name,
    )


@router.post("", response_model=ExemptionOut, status_code=status.HTTP_201_CREATED)
def grant(
    soldier_id: uuid.UUID,
    body: GrantRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionOut:
    s = _load_soldier(session, soldier_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, s))
    try:
        ex = svc.grant_exemption(
            session,
            soldier_id=soldier_id,
            exemption_type_id=body.exemption_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            is_medical=body.is_medical,
            actor_id=user.id,
        )
    except svc.ExemptionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(ex)
    return _out(session, ex, include_sensitive=True)


class GrantCommanderExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/commander-exemption", response_model=ExemptionOut, status_code=status.HTTP_201_CREATED)
def grant_commander_exemption_route(
    soldier_id: uuid.UUID,
    body: GrantCommanderExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionOut:
    s = _load_soldier(session, soldier_id)
    target_node = _node_of(session, s)

    from app.services.authority import duty_manager_exemption_immediate_apply_authorized

    allowed = user.role == "admin"
    if not allowed and is_duty_manager(session, user.id):
        allowed = duty_manager_exemption_immediate_apply_authorized(
            session, user=user, target_node=target_node,
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    try:
        ex = svc.grant_commander_exemption(
            session,
            soldier_id=soldier_id,
            exemption_type_id=body.exemption_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            actor_id=user.id,
        )
    except svc.ExemptionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(ex)
    return _out(session, ex, include_sensitive=True)


class RevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.delete("/{exemption_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def revoke(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    body: RevokeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    s = _load_soldier(session, soldier_id)
    from app.services.authority import request_cancellation_authorized

    if not request_cancellation_authorized(session, user=user, target_node=_node_of(session, s)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.revoke_exemption(session, exemption_id=exemption_id, reason=body.reason, actor_id=user.id)
    session.commit()


@router.post("/{exemption_id}/files", response_model=ExemptionFileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionFileOut:
    target, exemption = _load_exemption(session, soldier_id, exemption_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, target))
    data = await file.read()
    content_type = file.content_type or ""
    try:
        validate_exemption_file(content_type, data)
    except FileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    saved = SoldierExemptionFile(
        soldier_exemption_id=exemption.id,
        file_name=re.sub(r"[^\w.\-]", "_", (file.filename or "file")).replace("..", "_")[:200],
        content_type=content_type,
        data=data,
        uploaded_by=user.id,
    )
    session.add(saved)
    session.commit()
    session.refresh(saved)
    return _file_out(saved)


@router.get("/{exemption_id}/files", response_model=list[ExemptionFileOut])
def list_files(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionFileOut]:
    target, exemption = _load_exemption(session, soldier_id, exemption_id)
    _authorize_file_read(session, user, target, exemption)
    files = session.execute(
        select(SoldierExemptionFile)
        .where(SoldierExemptionFile.soldier_exemption_id == exemption.id)
        .order_by(SoldierExemptionFile.created_at)
    ).scalars().all()
    return [_file_out(file) for file in files]


@limiter.limit("30/minute")
@router.get("/{exemption_id}/files/{file_id}")
def download_file(
    request: Request,
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    file_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Response:
    target, exemption = _load_exemption(session, soldier_id, exemption_id)
    _authorize_file_read(session, user, target, exemption)
    file = session.get(SoldierExemptionFile, file_id)
    if file is None or file.soldier_exemption_id != exemption.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file_not_found")
    return Response(
        content=file.data,
        media_type=file.content_type,
        headers={"Content-Disposition": f'attachment; filename="{file.file_name}"'},
    )
