from __future__ import annotations

import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import (
    Action, authorize, can, can_see_private, can_view_medical_document, forbid_self_target, is_commander,
    is_duty_manager, scope_root_ids,
)
from app.rate_limit import limiter
from app.auth.deps import require_enrolled, require_password_changed
from app.db.models import ExemptionRequest, ExemptionRequestFile, HierarchyNode, Soldier, SoldierEnrollmentRequest
from app.db.session import get_session
from app.services.authority import (
    commander_can_grant_commander_exemption, dm_scope_covers_target, REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
)
from app.services.exemption_requests import (
    ExemptionRequestError,
    approve_commander_step,
    approve_duty_manager_step,
    count_pending_requests,
    list_own_requests,
    list_pending_requests,
    reject_request,
    submit_commander_escalation,
    submit_request,
)
from app.services.exemptions import ExemptionError

router = APIRouter(tags=["exemption-requests"])

from app.services.file_validation import FileValidationError, validate_exemption_file


class NearestApproverOut(BaseModel):
    id: uuid.UUID
    name: str


class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    exemption_type_id: uuid.UUID | None    # None when viewer cannot see private fields
    start_date: str | None
    end_date: str | None
    reason: str | None                      # None when viewer cannot see private fields
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str
    files: list[ExemptionFileOut] = []
    enrollment_request_id: uuid.UUID | None = None
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None
    can_approve_commander_step: bool = True
    can_approve_duty_manager_step: bool = True


class CreateExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str = Field(min_length=1, max_length=1000)


class CommanderEscalateRequest(BaseModel):
    official_exemption_type_id: uuid.UUID
    commander_exemption_type_id: uuid.UUID | None = None
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    apply_immediately: bool


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
    nearest_commander: NearestApproverOut | None = None,
    nearest_duty_manager: NearestApproverOut | None = None,
    can_approve_commander_step: bool = True,
    can_approve_duty_manager_step: bool = True,
) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        id=req.id,
        soldier_id=req.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        exemption_type_id=req.exemption_type_id if include_sensitive else None,
        start_date=req.start_date.isoformat() if req.start_date else None,
        end_date=req.end_date.isoformat() if req.end_date else None,
        reason=req.reason if include_sensitive else None,
        status=req.status,
        decided_by=req.decided_by,
        decision_note=req.decision_note,
        created_at=req.created_at.isoformat(),
        files=files or [],
        enrollment_request_id=req.enrollment_request_id,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve_commander_step=can_approve_commander_step,
        can_approve_duty_manager_step=can_approve_duty_manager_step,
    )


def _exemption_approval_flags(
    session: Session, user: Soldier, target_node: HierarchyNode | None
) -> tuple[bool, bool]:
    """Mirror the authorization checks in approve_exemption_request_commander_step
    and approve_exemption_request_duty_manager_step, so pending-list responses can
    tell the frontend whether the current viewer's approve buttons would actually
    succeed, instead of failing 403 only after the click.

    Commander-step mirrors `authorize(session, user, Action.CONSTRAINT_APPROVE, ...)`
    exactly via `can()` — note CONSTRAINT_APPROVE is in both _DM_ACTIONS and
    _COMMANDER_ACTIONS, so an in-scope duty manager (not just a commander) can
    also successfully call approve-commander; using a bare `is_commander(...)`
    check here would produce a false negative (hide a button that would actually
    succeed) for that case.
    """
    if user.role == "admin":
        return True, True
    roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    can_commander_step = can(
        user, Action.CONSTRAINT_APPROVE, target_node=target_node, roots=roots,
        is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
    )
    can_dm_step = user_is_duty_manager and dm_scope_covers_target(
        session, scope_root_ids=roots, target_node=target_node,
        required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
    )
    return can_commander_step, can_dm_step


def _nearest_approvers(
    session: Session, soldier_id: uuid.UUID
) -> tuple[NearestApproverOut | None, NearestApproverOut | None]:
    from app.services.approval_scope import nearest_commander_for_soldier, nearest_duty_manager_for_soldier

    cmd_id = nearest_commander_for_soldier(session, soldier_id)
    dm_id = nearest_duty_manager_for_soldier(session, soldier_id)
    cmd = session.get(Soldier, cmd_id) if cmd_id else None
    dm = session.get(Soldier, dm_id) if dm_id else None
    return (
        NearestApproverOut(id=cmd.id, name=cmd.full_name) if cmd else None,
        NearestApproverOut(id=dm.id, name=dm.full_name) if dm else None,
    )


@router.post("/me/exemption-requests", response_model=ExemptionRequestOut, status_code=status.HTTP_201_CREATED)
def create_exemption_request(
    body: CreateExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_enrolled),
) -> ExemptionRequestOut:
    try:
        req = submit_request(
            session,
            soldier_id=user.id,
            exemption_type_id=body.exemption_type_id,
            start_date=date.fromisoformat(body.start_date) if body.start_date else None,
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            reason=body.reason,
        )
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, user.id)
    return _out(req, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


@router.get("/me/exemption-requests", response_model=list[ExemptionRequestOut])
def get_my_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, user.id)
    return [
        _out(r, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)
        for r in list_own_requests(session, user.id)
    ]


@router.get("/exemption-requests/pending", response_model=list[ExemptionRequestOut])
def get_pending_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return []

    from app.db.models import DutyManagerScope, HierarchyLevelType
    from app.services.settings_loader import get_setting, SettingNotFound

    try:
        min_dm_rank = int(get_setting(session, "enrollment.min_dm_level_rank"))
    except SettingNotFound:
        min_dm_rank = 0

    # Compute the maximum level rank of this user's DM scope nodes
    user_dm_node_ids = session.execute(
        select(DutyManagerScope.hierarchy_node_id).where(
            DutyManagerScope.duty_manager_id == user.id
        )
    ).scalars().all()
    user_max_scope_rank = 0
    for nid in user_dm_node_ids:
        n = session.get(HierarchyNode, nid)
        if n:
            lt = session.execute(
                select(HierarchyLevelType).where(HierarchyLevelType.key == n.level)
            ).scalar_one_or_none()
            if lt and lt.rank > user_max_scope_rank:
                user_max_scope_rank = lt.rank
    user_can_see_enrollment_exemptions = (
        user.role == "admin" or user_max_scope_rank >= min_dm_rank
    )

    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    enrolled_ids = set(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    pending_enrollment_ids = set(
        session.execute(
            select(SoldierEnrollmentRequest.soldier_id).where(
                SoldierEnrollmentRequest.status == "pending",
                SoldierEnrollmentRequest.requested_node_id.in_(select(subq.c.id)),
            )
        )
        .scalars()
        .all()
    )
    soldier_ids = list(enrolled_ids | pending_enrollment_ids)
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
        if r.enrollment_request_id and not user_can_see_enrollment_exemptions:
            continue
        s = soldiers_by_id.get(r.soldier_id)
        soldier_name = s.full_name if s else str(r.soldier_id)[:8]
        node = nodes_by_id.get(s.hierarchy_node_id) if s and s.hierarchy_node_id else None
        node_name = node.name if node else None
        include_sensitive = s is not None and can_see_private(session, user, s)
        nearest_commander, nearest_duty_manager = _nearest_approvers(session, r.soldier_id)
        can_commander_step, can_dm_step = _exemption_approval_flags(session, user, node)
        result.append(
            _out(
                r, soldier_name=soldier_name, node_name=node_name, files=files_by_req.get(r.id, []),
                include_sensitive=include_sensitive, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                can_approve_commander_step=can_commander_step, can_approve_duty_manager_step=can_dm_step,
            )
        )
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
    enrolled_ids = set(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    pending_enrollment_ids = set(
        session.execute(
            select(SoldierEnrollmentRequest.soldier_id).where(
                SoldierEnrollmentRequest.status == "pending",
                SoldierEnrollmentRequest.requested_node_id.in_(select(subq.c.id)),
            )
        )
        .scalars()
        .all()
    )
    soldier_ids = list(enrolled_ids | pending_enrollment_ids)
    return {"count": count_pending_requests(session, soldier_ids)}


class PatchExemptionBody(BaseModel):
    exemption_type_id: uuid.UUID | None = None
    start_date: str | None = None
    end_date: str | None = None
    reason: str | None = None


@router.patch("/exemption-requests/{request_id}", response_model=ExemptionRequestOut)
def patch_exemption_request(
    request_id: uuid.UUID,
    body: PatchExemptionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    if req.status not in ("pending_commander", "pending_duty_manager"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exemption_request_not_pending")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    if body.exemption_type_id is not None:
        from app.db.models import ExemptionType
        new_type = session.get(ExemptionType, body.exemption_type_id)
        if new_type is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_type_not_found")
        if new_type.is_commander_exemption:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="commander_exemption_not_requestable")
        req.exemption_type_id = body.exemption_type_id
    if body.start_date is not None:
        from datetime import date as _date
        req.start_date = _date.fromisoformat(body.start_date)
    if body.end_date is not None:
        from datetime import date as _date
        if body.end_date == "":
            req.end_date = None
        else:
            req.end_date = _date.fromisoformat(body.end_date)
    if body.reason is not None:
        req.reason = body.reason or None
    session.commit()
    if req.enrollment_request_id:
        from app.services.enrollment import try_activate
        try_activate(session, req.enrollment_request_id)
        session.commit()
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, req.soldier_id)
    return _out(req, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


@router.post("/exemption-requests/{request_id}/approve-commander", response_model=ExemptionRequestOut)
def approve_exemption_request_commander_step(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    forbid_self_target(user, req.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    try:
        result = approve_commander_step(session, request_id, approved_by=user.id)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, result.soldier_id)
    return _out(result, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


@router.post("/exemption-requests/{request_id}/approve-duty-manager", response_model=ExemptionRequestOut)
def approve_exemption_request_duty_manager_step(
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
    forbid_self_target(user, req.soldier_id)

    from app.auth.authz import is_duty_manager, scope_root_ids
    if user.role != "admin":
        if not is_duty_manager(session, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        roots = scope_root_ids(session, user)
        if not dm_scope_covers_target(
            session, scope_root_ids=roots, target_node=target_node,
            required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_scope_level_for_exemption_approval")

    try:
        result = approve_duty_manager_step(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, result.soldier_id)
    return _out(result, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


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
    forbid_self_target(user, req.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    try:
        result = reject_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, result.soldier_id)
    return _out(result, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


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
    data = await file.read()
    try:
        validate_exemption_file(file.content_type or "", data)
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ef = ExemptionRequestFile(
        exemption_request_id=request_id,
        file_name=re.sub(r"[^\w.\-]", "_", (file.filename or "file")).replace("..", "_")[:200],
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


@limiter.limit("30/minute")
@router.get("/exemption-requests/{request_id}/files/{file_id}")
def download_exemption_file(
    request: Request,
    request_id: uuid.UUID,
    file_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Response:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    if req.soldier_id != user.id:
        target_soldier = session.get(Soldier, req.soldier_id)
        if target_soldier is None or not can_view_medical_document(session, user, target_soldier):
            raise HTTPException(status_code=403, detail="no_permission")
    ef = session.get(ExemptionRequestFile, file_id)
    if ef is None or ef.exemption_request_id != request_id:
        raise HTTPException(status_code=404, detail="file_not_found")
    return Response(
        content=ef.data,
        media_type=ef.content_type,
        headers={"Content-Disposition": f'attachment; filename="{ef.file_name}"'},
    )


@router.post(
    "/soldiers/{soldier_id}/exemptions/commander-escalate",
    response_model=ExemptionRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def escalate_commander_exemption_route(
    soldier_id: uuid.UUID,
    body: CommanderEscalateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    target_soldier = session.get(Soldier, soldier_id)
    if target_soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    target_node = (
        session.get(HierarchyNode, target_soldier.hierarchy_node_id)
        if target_soldier.hierarchy_node_id
        else None
    )

    allowed = user.role == "admin"
    if not allowed and is_duty_manager(session, user.id):
        from app.auth.authz import _node_in_scope
        allowed = _node_in_scope(target_node, scope_root_ids(session, user))
    if not allowed and is_commander(session, user.id):
        from app.auth.authz import _node_in_scope
        in_scope = _node_in_scope(target_node, scope_root_ids(session, user))
        allowed = in_scope and commander_can_grant_commander_exemption(
            session, commander_id=user.id,
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    try:
        req = submit_commander_escalation(
            session,
            soldier_id=soldier_id,
            official_exemption_type_id=body.official_exemption_type_id,
            commander_exemption_type_id=body.commander_exemption_type_id,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            reason=body.reason,
            apply_immediately=body.apply_immediately,
            actor_id=user.id,
        )
    except (ExemptionRequestError, ExemptionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _out(req, include_sensitive=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


@router.get("/soldiers/{soldier_id}/exemption-requests", response_model=list[ExemptionRequestOut])
def get_soldier_exemption_request_history(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    target_soldier = session.get(Soldier, soldier_id)
    if target_soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if target_soldier.id != user.id:
        target_node = (
            session.get(HierarchyNode, target_soldier.hierarchy_node_id)
            if target_soldier.hierarchy_node_id
            else None
        )
        authorize(session, user, Action.EXEMPTION_READ, target_node=target_node)
    include_sensitive = can_see_private(session, user, target_soldier)
    reqs = session.execute(
        select(ExemptionRequest)
        .where(ExemptionRequest.soldier_id == soldier_id)
        .order_by(ExemptionRequest.created_at.desc())
    ).scalars().all()
    req_ids = [r.id for r in reqs]
    all_files = (
        session.execute(
            select(ExemptionRequestFile).where(ExemptionRequestFile.exemption_request_id.in_(req_ids))
        ).scalars().all()
        if req_ids
        else []
    )
    files_by_req: dict[uuid.UUID, list[ExemptionFileOut]] = {}
    for f in all_files:
        files_by_req.setdefault(f.exemption_request_id, []).append(
            ExemptionFileOut(id=f.id, file_name=f.file_name, content_type=f.content_type, created_at=f.created_at.isoformat())
        )
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    target_node = (
        session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier.hierarchy_node_id else None
    )
    can_commander_step, can_dm_step = _exemption_approval_flags(session, user, target_node)
    return [
        _out(
            r, soldier_name=target_soldier.full_name, files=files_by_req.get(r.id, []), include_sensitive=include_sensitive,
            nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
            can_approve_commander_step=can_commander_step, can_approve_duty_manager_step=can_dm_step,
        )
        for r in reqs
    ]
