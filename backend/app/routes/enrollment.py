from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import ExemptionRequest, HierarchyNode, NotificationType, Soldier, SoldierEnrollmentRequest
from app.db.session import get_session
from app.services import enrollment as svc
from app.services.eligibility import derive_is_career, validate_rank_track_compatibility
from app.services.notifications import create_notification
from app.services.rank_advancement import compute_initial_next_rank_date, resolve_track
from app.services.authority import RankAdvancementEditScope, rank_advancement_edit_authorized
from app.validation import is_valid_israeli_phone

router = APIRouter(prefix="/enrollment-requests", tags=["enrollment"])

# Hebrew labels for the soldier-facing "what changed" notification, keyed by
# the same PatchEnrollmentBody field names.
_EDITABLE_FIELD_LABELS: dict[str, str] = {
    "full_name": "שם מלא",
    "personal_number": "מספר אישי",
    "phone": "טלפון",
    "email": "אימייל",
    "rank": "דרגה",
    "rank_track": "מסלול דרגה",
    "is_officer": "קצין",
    "gender": "מגדר",
    "enlistment_date": "תאריך גיוס",
    "mandatory_end_date": "סיום חובה",
    "discharge_date": "שחרור",
    "last_mitvahim_date": "מטווח אחרון",
    "last_alal_date": 'אל"ל אחרון',
}


class NearestApproverOut(BaseModel):
    id: uuid.UUID
    name: str


class EnrollmentExemptionOut(BaseModel):
    id: uuid.UUID
    exemption_type_id: uuid.UUID | None
    start_date: str | None
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
    rank_track: str | None = None
    is_officer: bool | None = None
    is_career: bool = False
    can_edit_rank_advancement: bool = False
    gender: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    exemption_requests: list[EnrollmentExemptionOut] = []
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None


class DecisionBody(BaseModel):
    decision_note: str | None = None


class PatchEnrollmentBody(BaseModel):
    full_name: str | None = None
    personal_number: str | None = None
    requested_node_id: uuid.UUID | None = None
    phone: str | None = None
    email: str | None = None
    rank: str | None = None
    rank_track: str | None = None
    is_officer: bool | None = None
    gender: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str | None) -> str | None:
        if v and not is_valid_israeli_phone(v):
            raise ValueError("invalid_israeli_phone")
        return v


def _nearest_approvers_for_node(
    session: Session, node_id: uuid.UUID
) -> tuple[NearestApproverOut | None, NearestApproverOut | None]:
    """Nearest commander/duty-manager for an enrollment request.

    Enrollment requests reference a soldier who has not been placed into the
    hierarchy yet — `Soldier.hierarchy_node_id` stays unset until the request
    is fully approved (see `app.services.enrollment.try_activate`) — so the
    shared `nearest_commander_for_soldier`/`nearest_duty_manager_for_soldier`
    helpers (which key off `soldier.hierarchy_node_id`) would always return
    None for a pending request. Walk the *requested* node's path instead,
    mirroring the same nearest-first logic in `app.services.approval_scope`.
    """
    from app.db.models import DutyManagerScope

    node = session.get(HierarchyNode, node_id)
    if node is None or not node.path_ids:
        return None, None
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
        ).scalars().all()
    }
    cmd_id: uuid.UUID | None = None
    for nid in reversed(node.path_ids):
        n = nodes_by_id.get(nid)
        if n and n.commander_id:
            cmd_id = n.commander_id
            break

    scopes = session.execute(
        select(DutyManagerScope).where(DutyManagerScope.hierarchy_node_id.in_(node.path_ids))
    ).scalars().all()
    by_node: dict[uuid.UUID, list[uuid.UUID]] = {}
    for sc in scopes:
        by_node.setdefault(sc.hierarchy_node_id, []).append(sc.duty_manager_id)
    dm_id: uuid.UUID | None = None
    for nid in reversed(node.path_ids):
        ids = by_node.get(nid, [])
        if ids:
            names_by_id = {
                s.id: s.full_name
                for s in session.execute(select(Soldier).where(Soldier.id.in_(ids))).scalars().all()
            }
            dm_id = sorted(ids, key=lambda i: names_by_id.get(i, ""))[0]
            break

    cmd = session.get(Soldier, cmd_id) if cmd_id else None
    dm = session.get(Soldier, dm_id) if dm_id else None
    return (
        NearestApproverOut(id=cmd.id, name=cmd.full_name) if cmd else None,
        NearestApproverOut(id=dm.id, name=dm.full_name) if dm else None,
    )


def _soldier_to_out(
    session: Session,
    r: SoldierEnrollmentRequest,
    s: Soldier,
    node_name: str | None,
    exemptions: list[ExemptionRequest],
    nearest_commander: NearestApproverOut | None = None,
    nearest_duty_manager: NearestApproverOut | None = None,
    *,
    rank_scope: RankAdvancementEditScope,
) -> EnrollmentRequestOut:
    return EnrollmentRequestOut(
        id=r.id, soldier_id=r.soldier_id,
        soldier_name=s.full_name,
        soldier_personal_number=s.personal_number,
        requested_node_id=r.requested_node_id,
        requested_node_name=node_name,
        status=r.status, decided_by=r.decided_by, decision_note=r.decision_note,
        phone=s.phone, email=s.email, rank=s.rank,
        is_officer=s.is_officer, rank_track=s.rank_track, is_career=s.is_career,
        can_edit_rank_advancement=rank_scope.authorized(
            session.get(HierarchyNode, r.requested_node_id),
        ),
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
                start_date=er.start_date.isoformat() if er.start_date else None,
                end_date=er.end_date.isoformat() if er.end_date else None,
                reason=er.reason,
                status=er.status,
            )
            for er in exemptions
        ],
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
    )


def _load_reqs(
    session: Session, reqs: list[SoldierEnrollmentRequest], *, user: Soldier
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

    rank_scope = RankAdvancementEditScope(session, user=user)
    result = []
    for r in reqs:
        s = soldiers.get(r.soldier_id)
        if not s:
            continue
        node_name = nodes[r.requested_node_id].name if r.requested_node_id in nodes else None
        nearest_commander, nearest_duty_manager = _nearest_approvers_for_node(session, r.requested_node_id)
        result.append(
            _soldier_to_out(
                session, r, s, node_name, exemptions_by_enrollment.get(r.id, []),
                nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                rank_scope=rank_scope,
            )
        )
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
    return _load_reqs(session, list(reqs), user=user)


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

    # The "save and approve" UI flow always resubmits rank/rank_track/is_officer
    # alongside the approval, even when the reviewer never touched them. Gating
    # on mere presence in the body (rather than an actual value change) would
    # wrongly demand the stricter rank_advancement_edit_authorized check on every
    # approval, blocking commanders who have full ENROLLMENT_APPROVE scope over
    # the node but sit below the "מדור"-or-above bar that check requires.
    def _rank_field_value(field: str, raw: object) -> object:
        if field == "rank":
            return raw or None
        if field == "is_officer":
            return bool(raw)
        return raw

    rank_advancement_fields = {"rank", "rank_track", "is_officer"}
    touched_rank_fields = rank_advancement_fields & body.model_fields_set
    rank_fields_changed = any(
        _rank_field_value(f, getattr(body, f)) != _rank_field_value(f, getattr(s, f))
        for f in touched_rank_fields
    )
    if rank_fields_changed:
        if not rank_advancement_edit_authorized(session, user=user, target_node=target_node):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        if body.requested_node_id is not None:
            destination_node = session.get(HierarchyNode, body.requested_node_id)
            if destination_node is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node_not_found")
            if not rank_advancement_edit_authorized(session, user=user, target_node=destination_node):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    changed_fields: list[str] = []

    def _apply(field: str, new_value: object) -> None:
        if new_value != getattr(s, field):
            changed_fields.append(field)
        setattr(s, field, new_value)

    if body.full_name is not None:
        _apply("full_name", body.full_name)
    if body.personal_number is not None:
        _apply("personal_number", body.personal_number)
    if body.phone is not None:
        _apply("phone", body.phone or None)
    if body.email is not None:
        _apply("email", body.email or None)
    if body.rank is not None:
        _apply("rank", body.rank or None)
    if body.rank_track is not None:
        _apply("rank_track", body.rank_track)
    if body.is_officer is not None:
        _apply("is_officer", body.is_officer)
    if body.gender is not None:
        _apply("gender", body.gender or None)
    if body.enlistment_date is not None:
        _apply("enlistment_date", date.fromisoformat(body.enlistment_date) if body.enlistment_date else None)
    if body.mandatory_end_date is not None:
        _apply("mandatory_end_date", date.fromisoformat(body.mandatory_end_date) if body.mandatory_end_date else None)
    if body.discharge_date is not None:
        _apply("discharge_date", date.fromisoformat(body.discharge_date) if body.discharge_date else None)
    if body.last_mitvahim_date is not None:
        _apply("last_mitvahim_date", date.fromisoformat(body.last_mitvahim_date) if body.last_mitvahim_date else None)
    if body.last_alal_date is not None:
        _apply("last_alal_date", date.fromisoformat(body.last_alal_date) if body.last_alal_date else None)

    if {"rank", "rank_track"} & set(changed_fields):
        resolved_track = resolve_track(s.rank, s.rank_track)
        if s.rank is not None and s.rank_track is not None and resolved_track != s.rank_track:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rank_track_invalid")
        s.rank_track = resolved_track
        s.is_officer = resolved_track != "enlisted" if resolved_track is not None else s.is_officer
        s.is_career = derive_is_career(s.rank, s.mandatory_end_date, s.discharge_date)
        try:
            validate_rank_track_compatibility(s.rank, s.is_career)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if s.rank is not None:
            s.current_rank_since = s.enlistment_date or date.today()
            s.next_rank_date = compute_initial_next_rank_date(
                session,
                rank=s.rank,
                enlistment_date=s.enlistment_date,
                fallback_since=s.current_rank_since,
                track=s.rank_track,
            )
            s.next_rank_date_overridden = False

    if changed_fields:
        labels = [_EDITABLE_FIELD_LABELS[f] for f in changed_fields]
        create_notification(
            session,
            soldier_id=s.id,
            type=NotificationType.enrollment_fields_edited,
            title="פרטי הקליטה שלך עודכנו",
            body=f"השדות שעודכנו: {', '.join(labels)}",
            reference_type="soldier_enrollment_request",
            reference_id=req.id,
            actor_id=user.id,
        )

    if body.requested_node_id is not None:
        new_node = session.get(HierarchyNode, body.requested_node_id)
        if new_node is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node_not_found")
        authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=new_node)
        req.requested_node_id = body.requested_node_id
    session.commit()
    exemptions = session.execute(
        select(ExemptionRequest).where(ExemptionRequest.enrollment_request_id == req.id)
    ).scalars().all()
    node = session.get(HierarchyNode, req.requested_node_id)
    nearest_commander, nearest_duty_manager = _nearest_approvers_for_node(session, req.requested_node_id)
    rank_scope = RankAdvancementEditScope(session, user=user)
    return _soldier_to_out(
        session, req, s, node.name if node else None, list(exemptions),
        nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
        rank_scope=rank_scope,
    )


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
