from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import ExemptionRequest, HierarchyNode, Soldier, SoldierEnrollmentRequest
from app.db.session import get_session
from app.services import enrollment as svc

router = APIRouter(prefix="/enrollment-requests", tags=["enrollment"])


class EnrollmentExemptionOut(BaseModel):
    id: uuid.UUID
    exemption_type_id: uuid.UUID | None
    start_date: str
    end_date: str | None
    reason: str | None
    status: str


class EnrollmentRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    soldier_personal_number: str
    requested_node_id: uuid.UUID
    requested_node_name: str | None = None
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    phone: str | None = None
    email: str | None = None
    rank: str | None = None
    is_officer: bool | None = None
    is_career: bool = False
    gender: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    exemption_requests: list[EnrollmentExemptionOut] = []


class DecisionBody(BaseModel):
    decision_note: str | None = None


class PatchEnrollmentBody(BaseModel):
    full_name: str | None = None
    personal_number: str | None = None
    requested_node_id: uuid.UUID | None = None
    phone: str | None = None
    email: str | None = None
    rank: str | None = None
    is_officer: bool | None = None
    is_career: bool | None = None
    gender: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None


def _soldier_to_out(
    r: SoldierEnrollmentRequest,
    s: Soldier,
    node_name: str | None,
    exemptions: list[ExemptionRequest],
) -> EnrollmentRequestOut:
    return EnrollmentRequestOut(
        id=r.id, soldier_id=r.soldier_id,
        soldier_name=s.full_name,
        soldier_personal_number=s.personal_number,
        requested_node_id=r.requested_node_id,
        requested_node_name=node_name,
        status=r.status, decided_by=r.decided_by, decision_note=r.decision_note,
        phone=s.phone, email=s.email, rank=s.rank,
        is_officer=s.is_officer, is_career=s.is_career,
        gender=s.gender,
        enlistment_date=s.enlistment_date.isoformat() if s.enlistment_date else None,
        mandatory_end_date=s.mandatory_end_date.isoformat() if s.mandatory_end_date else None,
        discharge_date=s.discharge_date.isoformat() if s.discharge_date else None,
        last_mitvahim_date=s.last_mitvahim_date.isoformat() if s.last_mitvahim_date else None,
        last_alal_date=s.last_alal_date.isoformat() if s.last_alal_date else None,
        exemption_requests=[
            EnrollmentExemptionOut(
                id=er.id,
                exemption_type_id=er.exemption_type_id,
                start_date=er.start_date.isoformat(),
                end_date=er.end_date.isoformat() if er.end_date else None,
                reason=er.reason,
                status=er.status,
            )
            for er in exemptions
        ],
    )


def _load_reqs(
    session: Session, reqs: list[SoldierEnrollmentRequest]
) -> list[EnrollmentRequestOut]:
    if not reqs:
        return []
    soldier_ids = {r.soldier_id for r in reqs}
    soldiers = {
        s.id: s
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_(soldier_ids))
        ).scalars().all()
    }
    node_ids = {r.requested_node_id for r in reqs}
    nodes = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
        ).scalars().all()
    }
    req_ids = [r.id for r in reqs]
    exemptions_by_enrollment: dict[uuid.UUID, list[ExemptionRequest]] = {}
    for er in session.execute(
        select(ExemptionRequest).where(
            ExemptionRequest.enrollment_request_id.in_(req_ids)
        )
    ).scalars().all():
        exemptions_by_enrollment.setdefault(er.enrollment_request_id, []).append(er)

    result = []
    for r in reqs:
        s = soldiers.get(r.soldier_id)
        if not s:
            continue
        node_name = nodes[r.requested_node_id].name if r.requested_node_id in nodes else None
        result.append(_soldier_to_out(r, s, node_name, exemptions_by_enrollment.get(r.id, [])))
    return result


@router.get("/pending", response_model=list[EnrollmentRequestOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EnrollmentRequestOut]:
    if user.role == "admin":
        reqs = session.execute(
            select(SoldierEnrollmentRequest).where(
                SoldierEnrollmentRequest.status == "pending"
            )
        ).scalars().all()
    else:
        roots = scope_root_ids(session, user)
        reqs = svc.list_pending_for_node_ids(session, roots)
    return _load_reqs(session, list(reqs))


@router.patch("/{request_id}", response_model=EnrollmentRequestOut)
def patch_enrollment(
    request_id: uuid.UUID,
    body: PatchEnrollmentBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EnrollmentRequestOut:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if req.status not in ("pending", "commander_approved"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already decided")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    s = session.get(Soldier, req.soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="soldier not found")
    if body.full_name is not None:
        s.full_name = body.full_name
    if body.personal_number is not None:
        s.personal_number = body.personal_number
    if body.phone is not None:
        s.phone = body.phone or None
    if body.email is not None:
        s.email = body.email or None
    if body.rank is not None:
        s.rank = body.rank or None
    if body.is_officer is not None:
        s.is_officer = body.is_officer
    if body.is_career is not None:
        s.is_career = body.is_career
    if body.gender is not None:
        s.gender = body.gender or None
    if body.enlistment_date is not None:
        s.enlistment_date = date.fromisoformat(body.enlistment_date) if body.enlistment_date else None
    if body.mandatory_end_date is not None:
        s.mandatory_end_date = date.fromisoformat(body.mandatory_end_date) if body.mandatory_end_date else None
    if body.discharge_date is not None:
        s.discharge_date = date.fromisoformat(body.discharge_date) if body.discharge_date else None
    if body.last_mitvahim_date is not None:
        s.last_mitvahim_date = date.fromisoformat(body.last_mitvahim_date) if body.last_mitvahim_date else None
    if body.last_alal_date is not None:
        s.last_alal_date = date.fromisoformat(body.last_alal_date) if body.last_alal_date else None
    if body.requested_node_id is not None:
        if session.get(HierarchyNode, body.requested_node_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
        req.requested_node_id = body.requested_node_id
    session.flush()
    exemptions = session.execute(
        select(ExemptionRequest).where(ExemptionRequest.enrollment_request_id == req.id)
    ).scalars().all()
    node = session.get(HierarchyNode, req.requested_node_id)
    return _soldier_to_out(req, s, node.name if node else None, list(exemptions))


@router.post("/{request_id}/approve")
def approve(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.approve_enrollment(
            session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note
        )
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{request_id}/reject")
def reject(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not body.decision_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="decision_note required"
        )
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.reject_enrollment(
            session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note
        )
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
