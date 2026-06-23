from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can_see_private, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import ExemptionRequest, ExemptionRequestFile, HierarchyNode, Soldier
from app.db.session import get_session
from app.services.settings_loader import exemptions_require_rasn
from app.services.exemption_requests import (
    ExemptionRequestError,
    approve_request,
    count_pending_requests,
    list_own_requests,
    list_pending_requests,
    reject_request,
    submit_request,
)

router = APIRouter(tags=["exemption-requests"])


class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    exemption_type_id: uuid.UUID | None    # None when viewer cannot see private fields
    start_date: str
    end_date: str | None
    reason: str | None                      # None when viewer cannot see private fields
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str
    files: list[ExemptionFileOut] = []


class CreateExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str | None = None


class ApproveRejectRequest(BaseModel):
    decision_note: str | None = None


class ExemptionFileOut(BaseModel):
    id: uuid.UUID
    file_name: str
    content_type: str
    created_at: str


def _out(
    req: ExemptionRequest,
    soldier_name: str = "",
    node_name: str | None = None,
    files: list[ExemptionFileOut] | None = None,
    include_sensitive: bool = True,
) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        id=req.id,
        soldier_id=req.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        exemption_type_id=req.exemption_type_id if include_sensitive else None,
        start_date=req.start_date.isoformat(),
        end_date=req.end_date.isoformat() if req.end_date else None,
        reason=req.reason if include_sensitive else None,
        status=req.status,
        decided_by=req.decided_by,
        decision_note=req.decision_note,
        created_at=req.created_at.isoformat(),
        files=files or [],
    )


@router.post("/me/exemption-requests", response_model=ExemptionRequestOut, status_code=status.HTTP_201_CREATED)
def create_exemption_request(
    body: CreateExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    try:
        req = submit_request(
            session,
            soldier_id=user.id,
            exemption_type_id=body.exemption_type_id,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            reason=body.reason,
        )
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(req, include_sensitive=True)


@router.get("/me/exemption-requests", response_model=list[ExemptionRequestOut])
def get_my_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    return [_out(r, include_sensitive=True) for r in list_own_requests(session, user.id)]


@router.get("/exemption-requests/pending", response_model=list[ExemptionRequestOut])
def get_pending_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return []
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    soldier_ids = list(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    reqs = list_pending_requests(session, soldier_ids)
    if not reqs:
        return []
    req_soldier_ids = {r.soldier_id for r in reqs}
    soldiers_by_id = {
        s.id: s
        for s in session.execute(select(Soldier).where(Soldier.id.in_(req_soldier_ids))).scalars().all()
    }
    node_ids = {s.hierarchy_node_id for s in soldiers_by_id.values() if s.hierarchy_node_id}
    nodes_by_id = (
        {
            n.id: n
            for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }
        if node_ids
        else {}
    )
    req_ids = [r.id for r in reqs]
    all_files = session.execute(
        select(ExemptionRequestFile).where(ExemptionRequestFile.exemption_request_id.in_(req_ids))
    ).scalars().all()
    files_by_req: dict[uuid.UUID, list[ExemptionFileOut]] = {}
    for f in all_files:
        files_by_req.setdefault(f.exemption_request_id, []).append(
            ExemptionFileOut(id=f.id, file_name=f.file_name, content_type=f.content_type, created_at=f.created_at.isoformat())
        )
    result = []
    for r in reqs:
        s = soldiers_by_id.get(r.soldier_id)
        soldier_name = s.full_name if s else str(r.soldier_id)[:8]
        node_name = (
            nodes_by_id[s.hierarchy_node_id].name
            if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
            else None
        )
        include_sensitive = s is not None and can_see_private(session, user, s)
        result.append(_out(r, soldier_name=soldier_name, node_name=node_name, files=files_by_req.get(r.id, []), include_sensitive=include_sensitive))
    return result


@router.get("/exemption-requests/pending/count")
def get_pending_exemption_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return {"count": 0}
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    soldier_ids = list(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    return {"count": count_pending_requests(session, soldier_ids)}


@router.post("/exemption-requests/{request_id}/approve", response_model=ExemptionRequestOut)
def approve_exemption_request(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    if exemptions_require_rasn(session):
        RASN_AND_ABOVE = {"רסן", "סגן אלוף", "אלוף משנה", "אלוף", "תת אלוף"}
        if user.role not in ("duty_manager", "admin") and (user.rank is None or user.rank not in RASN_AND_ABOVE):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient_rank_for_exemption_approval",
            )
    try:
        result = approve_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result, include_sensitive=True)


@router.post("/exemption-requests/{request_id}/reject", response_model=ExemptionRequestOut)
def reject_exemption_request(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    if exemptions_require_rasn(session):
        RASN_AND_ABOVE = {"רסן", "סגן אלוף", "אלוף משנה", "אלוף", "תת אלוף"}
        if user.role not in ("duty_manager", "admin") and (user.rank is None or user.rank not in RASN_AND_ABOVE):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient_rank_for_exemption_approval",
            )
    try:
        result = reject_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result, include_sensitive=True)


@router.post(
    "/me/exemption-requests/{request_id}/files",
    response_model=ExemptionFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_exemption_file(
    request_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionFileOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None or req.soldier_id != user.id:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="invalid_file_type")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")
    ef = ExemptionRequestFile(
        exemption_request_id=request_id,
        file_name=file.filename or "file",
        content_type=file.content_type,
        data=data,
        uploaded_by=user.id,
    )
    session.add(ef)
    session.commit()
    return ExemptionFileOut(
        id=ef.id,
        file_name=ef.file_name,
        content_type=ef.content_type,
        created_at=ef.created_at.isoformat(),
    )


@router.get("/exemption-requests/{request_id}/files", response_model=list[ExemptionFileOut])
def list_exemption_files(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionFileOut]:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    if req.soldier_id != user.id:
        root_ids = scope_root_ids(session, user)
        if not root_ids:
            raise HTTPException(status_code=403, detail="no_permission")
        target_soldier = session.get(Soldier, req.soldier_id)
        if target_soldier is None or target_soldier.hierarchy_node_id is None:
            raise HTTPException(status_code=403, detail="no_permission")
        node = session.get(HierarchyNode, target_soldier.hierarchy_node_id)
        if node is None or not any(r in (node.path_ids or []) for r in root_ids):
            raise HTTPException(status_code=403, detail="no_permission")
    files = session.execute(
        select(ExemptionRequestFile)
        .where(ExemptionRequestFile.exemption_request_id == request_id)
        .order_by(ExemptionRequestFile.created_at)
    ).scalars().all()
    return [
        ExemptionFileOut(id=f.id, file_name=f.file_name, content_type=f.content_type, created_at=f.created_at.isoformat())
        for f in files
    ]


@router.get("/exemption-requests/{request_id}/files/{file_id}")
def download_exemption_file(
    request_id: uuid.UUID,
    file_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Response:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    if req.soldier_id != user.id:
        root_ids = scope_root_ids(session, user)
        if not root_ids:
            raise HTTPException(status_code=403, detail="no_permission")
        target_soldier = session.get(Soldier, req.soldier_id)
        if target_soldier is None or target_soldier.hierarchy_node_id is None:
            raise HTTPException(status_code=403, detail="no_permission")
        node = session.get(HierarchyNode, target_soldier.hierarchy_node_id)
        if node is None or not any(r in (node.path_ids or []) for r in root_ids):
            raise HTTPException(status_code=403, detail="no_permission")
    ef = session.get(ExemptionRequestFile, file_id)
    if ef is None or ef.exemption_request_id != request_id:
        raise HTTPException(status_code=404, detail="file_not_found")
    return Response(
        content=ef.data,
        media_type=ef.content_type,
        headers={"Content-Disposition": f'attachment; filename="{ef.file_name}"'},
    )
