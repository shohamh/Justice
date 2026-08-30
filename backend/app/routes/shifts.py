from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_duty_manager_or_admin, require_password_changed
from sqlalchemy import delete as sa_delete, func
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink, DutyShift, DutyType, DutyLocation, HierarchyNode, NotificationType, PersonalConstraint, ShiftTemplate, Soldier, SwapRequest
from app.db.session import get_session
from app.services.notifications import create_notification
from app.services import shifts as svc
from app.services.algorithm_bridge import build_hierarchy_maps, load_soldier_inputs
from app.services.shift_quotas import ShiftQuotaError, compute_potential_split, compute_two_level_split, get_shift_quotas, set_shift_quotas
from app.services.shift_responsibility import auto_assign_responsibility
from app.algorithm.reserve import link_reserves

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shifts", tags=["shifts"])


class ShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int
    notes: str | None
    assigned_count: int
    reserve_assigned_count: int
    fill_status: str
    status: str = "active"
    reserve_count_override: int | None = None
    calculated_reserve_count: int | None = None
    eligible_node_ids: list[uuid.UUID] | None = None
    generated_from_template_id: uuid.UUID | None = None
    generated_from_template_name: str | None = None
    node_quotas: list["NodeQuotaOut"] = Field(default_factory=list)
    ineligible_count: int = 0
    required_range_type: str | None = None


class WeaponIneligibleCountOut(BaseModel):
    count: int


class NodeQuotaIn(BaseModel):
    hierarchy_node_id: uuid.UUID
    count: int


class NodeQuotaOut(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int


class SetQuotasRequest(BaseModel):
    quotas: list[NodeQuotaIn]


class SetQuotasResponse(BaseModel):
    quotas: list[NodeQuotaOut]


class CreateShiftRequest(BaseModel):
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: str | None = None
    end_time: str | None = None
    required_count: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=1000)
    reserve_count_override: int | None = Field(default=None, ge=0)
    eligible_node_ids: list[uuid.UUID] | None = None


class UpdateShiftRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    required_count: int | None = Field(default=None, ge=1)
    notes: str | None = None
    reserve_count_override: int | None = Field(default=None, ge=0)
    eligible_node_ids: list[uuid.UUID] | None = None


def _resolve_node_quotas(session: Session, shift_id: uuid.UUID) -> list[NodeQuotaOut]:
    entries = get_shift_quotas(session, shift_id=shift_id)
    if not entries:
        return []
    nodes = {
        n.id: n.name
        for n in session.execute(
            select(HierarchyNode).where(
                HierarchyNode.id.in_([e.hierarchy_node_id for e in entries])
            )
        ).scalars().all()
    }
    return [
        NodeQuotaOut(
            hierarchy_node_id=e.hierarchy_node_id,
            node_name=nodes.get(e.hierarchy_node_id, ""),
            count=e.count,
        )
        for e in entries
    ]


def _out(
    s: svc.ShiftWithFill,
    session: Session | None = None,
    template_name: str | None = None,
    node_quotas: list[NodeQuotaOut] | None = None,
    ineligible_count: int = 0,
) -> ShiftOut:
    calculated = None
    required_range_type = None
    if session is not None:
        from app.services.algorithm_bridge import reserve_count_for_shift
        from app.db.models import DutyShift as DutyShiftModel
        shift_obj = session.get(DutyShiftModel, s.id)
        if shift_obj is not None:
            calculated = reserve_count_for_shift(session, shift=shift_obj)
        duty_type = session.get(DutyType, s.duty_type_id)
        required_range_type = duty_type.required_range_type if duty_type is not None else None
    return ShiftOut(
        id=s.id,
        duty_type_id=s.duty_type_id,
        duty_location_id=s.duty_location_id,
        start_date=s.start_date,
        end_date=s.end_date,
        required_count=s.required_count,
        notes=s.notes,
        assigned_count=s.assigned_count,
        reserve_assigned_count=s.reserve_assigned_count,
        fill_status=s.fill_status,
        reserve_count_override=s.reserve_count_override,
        calculated_reserve_count=calculated,
        status=s.status,
        eligible_node_ids=s.eligible_node_ids,
        generated_from_template_id=s.generated_from_template_id,
        generated_from_template_name=template_name,
        node_quotas=node_quotas or [],
        ineligible_count=ineligible_count,
        required_range_type=required_range_type,
    )


def _load(session: Session, shift_id: uuid.UUID) -> DutyShift:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return shift


@router.get("", response_model=list[ShiftOut])
def list_shifts(
    date_from: date | None = None,
    date_to: date | None = None,
    duty_type_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ShiftOut]:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    shifts = svc.list_shifts(session, date_from=date_from, date_to=date_to, duty_type_id=duty_type_id)
    template_ids = {s.generated_from_template_id for s in shifts if s.generated_from_template_id}
    template_names: dict[uuid.UUID, str] = {}
    if template_ids:
        rows = session.execute(select(ShiftTemplate).where(ShiftTemplate.id.in_(template_ids))).scalars().all()
        template_names = {t.id: t.name for t in rows}

    shift_ids = [s.id for s in shifts]
    ineligible_counts: dict[uuid.UUID, int] = {}
    if shift_ids:
        count_rows = session.execute(
            select(DutyAssignment.duty_shift_id, func.count(DutyAssignment.id))
            .where(
                DutyAssignment.duty_shift_id.in_(shift_ids),
                DutyAssignment.weapon_ineligible.is_(True),
                DutyAssignment.status == "published",
            )
            .group_by(DutyAssignment.duty_shift_id)
        ).all()
        ineligible_counts = {row[0]: row[1] for row in count_rows}

    return [
        _out(
            s,
            session,
            template_name=template_names.get(s.generated_from_template_id) if s.generated_from_template_id else None,
            ineligible_count=ineligible_counts.get(s.id, 0),
        )
        for s in shifts
    ]


@router.get("/weapon-ineligible/count", response_model=WeaponIneligibleCountOut)
def weapon_ineligible_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> WeaponIneligibleCountOut:
    if user.role == "admin":
        cnt = session.execute(
            select(func.count(DutyAssignment.id)).where(
                DutyAssignment.weapon_ineligible.is_(True),
                DutyAssignment.status == "published",
            )
        ).scalar_one()
        return WeaponIneligibleCountOut(count=cnt)

    roots = scope_root_ids(session, user)
    if not roots:
        return WeaponIneligibleCountOut(count=0)

    # Subtree expansion mirrors app.services.constraints._scope_soldier_ids:
    # HierarchyNode.path_ids is the materialized ancestor-chain array, so an
    # `overlap` against the governed root ids matches the roots themselves
    # AND every descendant node, not just an exact-node id match.
    subtree_node_ids = select(HierarchyNode.id).where(HierarchyNode.path_ids.overlap(list(roots))).subquery()
    cnt = session.execute(
        select(func.count(DutyAssignment.id))
        .join(Soldier, Soldier.id == DutyAssignment.soldier_id)
        .where(
            DutyAssignment.weapon_ineligible.is_(True),
            DutyAssignment.status == "published",
            Soldier.hierarchy_node_id.in_(select(subtree_node_ids.c.id)),
        )
    ).scalar_one()
    return WeaponIneligibleCountOut(count=cnt)


class QuotaSplitEntry(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int
    weight: int


class QuotaSplitPreviewOut(BaseModel):
    entries: list[QuotaSplitEntry]


@router.get("/quota-split-preview", response_model=QuotaSplitPreviewOut)
def quota_split_preview(
    parent_node_id: uuid.UUID,
    required_count: int,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> QuotaSplitPreviewOut:
    parent = session.get(HierarchyNode, parent_node_id)
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        entries = compute_potential_split(
            session, parent_node_id=parent_node_id, required_count=required_count
        )
    except ShiftQuotaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return QuotaSplitPreviewOut(entries=[QuotaSplitEntry(**e) for e in entries])


class TwoLevelSplitEntry(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int
    weight: int
    parent_responsible_node_id: uuid.UUID


class TwoLevelSplitPreviewOut(BaseModel):
    entries: list[TwoLevelSplitEntry]


@router.get("/{shift_id}/quota-split-preview-two-level", response_model=TwoLevelSplitPreviewOut)
def quota_split_preview_two_level(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> TwoLevelSplitPreviewOut:
    shift = _load(session, shift_id)
    if not shift.eligible_node_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift_has_no_responsible_units")
    try:
        entries = compute_two_level_split(
            session, responsible_node_ids=list(shift.eligible_node_ids), required_count=shift.required_count
        )
    except ShiftQuotaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TwoLevelSplitPreviewOut(entries=[TwoLevelSplitEntry(**e) for e in entries])


class AutoAssignResponsibilityRequest(BaseModel):
    shift_ids: list[uuid.UUID]


class ResponsibilityAssignmentOut(BaseModel):
    shift_id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    node_name: str


class AutoAssignResponsibilityPreviewOut(BaseModel):
    assignments: list[ResponsibilityAssignmentOut]


@router.post("/auto-assign-responsibility/preview", response_model=AutoAssignResponsibilityPreviewOut)
def auto_assign_responsibility_preview(
    body: AutoAssignResponsibilityRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> AutoAssignResponsibilityPreviewOut:
    results = auto_assign_responsibility(session, shift_ids=body.shift_ids)
    return AutoAssignResponsibilityPreviewOut(
        assignments=[
            ResponsibilityAssignmentOut(shift_id=r.shift_id, hierarchy_node_id=r.hierarchy_node_id, node_name=r.node_name)
            for r in results
        ]
    )


@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(
    body: CreateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    try:
        shift = svc.create_shift(
            session,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            start_time=body.start_time,
            end_time=body.end_time,
            required_count=body.required_count,
            notes=body.notes,
            reserve_count_override=body.reserve_count_override,
            eligible_node_ids=body.eligible_node_ids,
            actor_id=user.id,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    result = svc.get_shift_fill(session, shift_id=shift.id)
    return _out(result, session)


@router.get("/{shift_id}", response_model=ShiftOut)
def get_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    result = svc.get_shift_fill(session, shift_id=shift_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return _out(result, session, node_quotas=_resolve_node_quotas(session, shift_id))


@router.put("/{shift_id}/quotas", response_model=SetQuotasResponse)
def put_shift_quotas(
    shift_id: uuid.UUID,
    body: SetQuotasRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> SetQuotasResponse:
    try:
        set_shift_quotas(
            session,
            shift_id=shift_id,
            quotas=[(q.hierarchy_node_id, q.count) for q in body.quotas],
            actor_id=actor.id,
        )
        session.commit()
    except ShiftQuotaError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SetQuotasResponse(quotas=_resolve_node_quotas(session, shift_id))


@router.patch("/{shift_id}", response_model=ShiftOut)
def update_shift(
    shift_id: uuid.UUID,
    body: UpdateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    extra: dict = {}
    if "notes" in body.model_fields_set:
        extra["notes"] = body.notes
    if "reserve_count_override" in body.model_fields_set:
        extra["reserve_count_override"] = body.reserve_count_override
    if "eligible_node_ids" in body.model_fields_set:
        extra["eligible_node_ids"] = body.eligible_node_ids
    try:
        svc.update_shift(
            session,
            shift=shift,
            start_date=body.start_date,
            end_date=body.end_date,
            required_count=body.required_count,
            actor_id=user.id,
            **extra,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(svc.get_shift_fill(session, shift_id=shift_id), session)


@router.post("/{shift_id}/cancel", response_model=ShiftOut)
def cancel_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    """Soft-cancel a shift. It stays in the DB but is excluded from the algorithm."""
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    shift.status = "cancelled"
    session.commit()
    return _out(svc.get_shift_fill(session, shift_id=shift_id), session)


@router.post("/{shift_id}/activate", response_model=ShiftOut)
def activate_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    """Re-activate a previously cancelled shift."""
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    shift.status = "active"
    session.commit()
    return _out(svc.get_shift_fill(session, shift_id=shift_id), session)


class BulkDeletePreview(BaseModel):
    shift_count: int
    assignment_count: int
    swap_count: int
    dismissal_count: int
    reserve_link_count: int
    shifts: list[dict]


def _shifts_in_range(session: Session, date_from: date, date_to: date) -> list[DutyShift]:
    return session.execute(
        select(DutyShift).where(
            DutyShift.start_date >= date_from,
            DutyShift.start_date <= date_to,
        ).order_by(DutyShift.start_date)
    ).scalars().all()


def _assignment_ids_for_shifts(session: Session, shift_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if not shift_ids:
        return []
    return list(session.execute(
        select(DutyAssignment.id).where(DutyAssignment.duty_shift_id.in_(shift_ids))
    ).scalars().all())


def _assignment_soldier_pairs_for_shifts(
    session: Session, shift_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    if not shift_ids:
        return []
    return list(session.execute(
        select(DutyAssignment.id, DutyAssignment.soldier_id).where(
            DutyAssignment.duty_shift_id.in_(shift_ids)
        )
    ).all())


@router.get("/bulk-delete/preview", response_model=BulkDeletePreview)
def bulk_delete_preview(
    date_from: date,
    date_to: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BulkDeletePreview:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    dt_map = {r.id: r.name for r in session.execute(select(DutyType)).scalars()}
    loc_map = {r.id: r.name for r in session.execute(select(DutyLocation)).scalars()}

    shifts = _shifts_in_range(session, date_from, date_to)
    shift_ids = [s.id for s in shifts]
    assignment_ids = _assignment_ids_for_shifts(session, shift_ids)

    swap_count = session.execute(
        select(func.count()).select_from(SwapRequest).where(SwapRequest.duty_assignment_id.in_(assignment_ids))
    ).scalar_one() if assignment_ids else 0

    dismissal_count = session.execute(
        select(func.count()).select_from(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids))
    ).scalar_one() if assignment_ids else 0

    reserve_link_count = session.execute(
        select(func.count()).select_from(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id.in_(assignment_ids) |
            DutyReserveLink.reserve_assignment_id.in_(assignment_ids)
        )
    ).scalar_one() if assignment_ids else 0

    return BulkDeletePreview(
        shift_count=len(shifts),
        assignment_count=len(assignment_ids),
        swap_count=swap_count,
        dismissal_count=dismissal_count,
        reserve_link_count=reserve_link_count,
        shifts=[
            {
                "id": str(s.id),
                "duty_type_name": dt_map.get(s.duty_type_id, ""),
                "duty_location_name": loc_map.get(s.duty_location_id, ""),
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat(),
                "required_count": s.required_count,
            }
            for s in shifts
        ],
    )


@router.delete("/bulk-delete", status_code=status.HTTP_200_OK)
def bulk_delete_shifts(
    date_from: date,
    date_to: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    shifts = _shifts_in_range(session, date_from, date_to)
    shift_ids = [s.id for s in shifts]
    pairs = _assignment_soldier_pairs_for_shifts(session, shift_ids)
    assignment_ids = [p[0] for p in pairs]

    if assignment_ids:
        session.execute(sa_delete(SwapRequest).where(SwapRequest.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id.in_(assignment_ids) |
            DutyReserveLink.reserve_assignment_id.in_(assignment_ids)
        ))
        session.execute(sa_delete(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids)))

    if shift_ids:
        session.execute(sa_delete(DutyShift).where(DutyShift.id.in_(shift_ids)))

    write_audit(
        session, actor_id=user.id, action="shift.bulk_delete", entity_type="duty_shift",
        after={"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
               "deleted_shifts": len(shift_ids), "deleted_assignments": len(assignment_ids)},
    )
    session.commit()

    # The bulk delete itself (shifts/assignments/audit row) already committed
    # above. Each notification is sent — and committed — independently so
    # that one bad item (e.g. one soldier out of many) doesn't prevent the
    # rest of the batch from being attempted: a failure here must never turn
    # a successful bulk delete into an unhandled 500 for the client, nor
    # silently drop notifications for unrelated assignments.
    for assignment_id, soldier_id in pairs:
        try:
            create_notification(
                session, soldier_id=soldier_id,
                type=NotificationType.assignment_removed,
                title="שיבוץ בוטל (מחיקת משמרות גורפת)",
                reference_type="duty_assignment", reference_id=assignment_id,
                actor_id=user.id,
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.error(
                "Failed to send assignment_removed notification for assignment %s "
                "after bulk shift delete",
                assignment_id,
                exc_info=True,
            )

    return {"deleted_shifts": len(shift_ids), "deleted_assignments": len(assignment_ids)}


@router.delete("/bulk-clear-assignments", status_code=status.HTTP_200_OK)
def bulk_clear_assignments(
    date_from: date,
    date_to: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    """Delete all assignments (and their cascading data) for shifts in range, keeping the shifts."""
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    shift_ids = [s.id for s in _shifts_in_range(session, date_from, date_to)]
    pairs = _assignment_soldier_pairs_for_shifts(session, shift_ids)
    assignment_ids = [p[0] for p in pairs]

    if assignment_ids:
        session.execute(sa_delete(SwapRequest).where(SwapRequest.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id.in_(assignment_ids) |
            DutyReserveLink.reserve_assignment_id.in_(assignment_ids)
        ))
        session.execute(sa_delete(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids)))

    write_audit(
        session, actor_id=user.id, action="shift.bulk_clear_assignments", entity_type="duty_shift",
        after={"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
               "cleared_assignments": len(assignment_ids)},
    )
    session.commit()

    # The bulk clear itself (assignments/audit row) already committed above.
    # Each notification is sent — and committed — independently so that one
    # bad item doesn't prevent the rest of the batch from being attempted: a
    # failure here must never turn a successful bulk clear into an
    # unhandled 500 for the client, nor silently drop notifications for
    # unrelated assignments.
    for assignment_id, soldier_id in pairs:
        try:
            create_notification(
                session, soldier_id=soldier_id,
                type=NotificationType.assignment_removed,
                title="שיבוץ בוטל (ניקוי משמרות גורף)",
                reference_type="duty_assignment", reference_id=assignment_id,
                actor_id=user.id,
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.error(
                "Failed to send assignment_removed notification for assignment %s "
                "after bulk shift assignment clear",
                assignment_id,
                exc_info=True,
            )

    return {"cleared_assignments": len(assignment_ids)}


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    try:
        svc.delete_shift(session, shift=shift, actor_id=user.id)
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


class PersonalConstraintWarningOut(BaseModel):
    reason: str
    start_date: date
    end_date: date
    decided_by: str | None
    decided_at: datetime | None


class ShiftCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    personal_number: str
    burden_share: float
    blocked: bool
    blocked_reason: str | None = None
    blocked_detail: str | None = None
    weapon_warning: bool = False
    hierarchy_path_ids: list[str] = []
    personal_constraint_warning: PersonalConstraintWarningOut | None = None


@router.get("/{shift_id}/candidates", response_model=list[ShiftCandidateOut])
def get_shift_candidates(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ShiftCandidateOut]:
    """Return eligible soldiers for a shift, sorted by burden-share ascending. Blocked soldiers (conflict/constraint) appear at end."""
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    from app.db.models import DutyType as _DutyType
    from app.services.weapon_eligibility import bulk_ineligible_duty_blocks
    from app.services.constraint_override_settings import manual_override_allowed

    override_allowed = manual_override_allowed(session)

    shift_duty_type = session.get(_DutyType, shift.duty_type_id)
    required_range_type = shift_duty_type.required_range_type if shift_duty_type else None

    soldier_map: dict[uuid.UUID, Soldier] = {
        s.id: s for s in session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    }

    # Soldiers already on THIS shift (exclude them entirely)
    already_on_shift: set[uuid.UUID] = set(
        session.execute(
            select(DutyAssignment.soldier_id).where(
                DutyAssignment.duty_shift_id == shift_id,
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        ).scalars().all()
    )

    # Soldiers with any overlapping published/draft assignment (conflict)
    blocked_by_assignment: set[uuid.UUID] = set(
        session.execute(
            select(DutyAssignment.soldier_id).where(
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
                DutyAssignment.start_date < shift.end_date,
                DutyAssignment.end_date > shift.start_date,
            )
        ).scalars().all()
    )

    from app.algorithm.types import node_in_scope
    from app.db.models import HierarchyNode
    node_map: dict[uuid.UUID, HierarchyNode] = {
        n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()
    }

    from app.algorithm.types import node_in_scope

    # Cohort scope: active soldiers not already on this shift whose hierarchy
    # path falls within the shift's eligible nodes. Later filters (duty-type
    # exemptions, constraints) still need SoldierInputs, so they are applied
    # after loading — but the loaded set is already force-size-independent.
    # Mirror node_in_scope semantics exactly: None = unrestricted, a list
    # (including empty) = path-intersection subtree check.
    candidate_soldier_ids: set[uuid.UUID] = set()
    if shift.eligible_node_ids is None:
        candidate_soldier_ids = {s.id for s in soldier_map.values()}
    else:
        eligible_id_set = {uuid.UUID(str(nid)) for nid in shift.eligible_node_ids}
        for soldier in soldier_map.values():
            node = node_map.get(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
            if node is not None and eligible_id_set & set(node.path_ids):
                candidate_soldier_ids.add(soldier.id)
    candidate_soldier_ids -= already_on_shift

    soldier_inputs = load_soldier_inputs(
        session, as_of=shift.start_date, soldier_ids=candidate_soldier_ids
    )

    from app.services.scoring import burden_shares_by_soldier

    candidate_soldiers = [soldier_map[si.id] for si in soldier_inputs if si.id in soldier_map]
    burden_share_by_id = burden_shares_by_soldier(session, candidate_soldiers)

    from app.db.models import ExemptionDutyTypeMap, ExemptionType, SoldierExemption
    from app.services.eligibility import duty_type_ineligibility_reason
    from app.services.settings_loader import SettingNotFound, get_setting

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except SettingNotFound:
            return default

    mitvahim_months = _setting_int("eligibility.mitvahim_months", 6)
    alal_months = _setting_int("eligibility.alal_months", 3)

    # Soldiers exempt from this specific duty type via a granted exemption
    # (as opposed to structurally ineligible per the duty type's requirements)
    # — used only to distinguish the two cases for blocked_detail, never to
    # expose the grant's own reason text.
    covering_etids: set[uuid.UUID] = set(
        session.execute(select(ExemptionType.id).where(ExemptionType.is_global.is_(True))).scalars().all()
    )
    covering_etids.update(
        session.execute(
            select(ExemptionDutyTypeMap.exemption_type_id).where(
                ExemptionDutyTypeMap.duty_type_id == shift.duty_type_id
            )
        ).scalars().all()
    )
    exempted_via_grant: set[uuid.UUID] = set()
    if covering_etids:
        exempted_via_grant = set(
            session.execute(
                select(SoldierExemption.soldier_id).where(
                    SoldierExemption.exemption_type_id.in_(covering_etids),
                    SoldierExemption.start_date <= shift.start_date,
                    or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= shift.start_date),
                )
            ).scalars().all()
        )

    weapon_ineligible: dict[uuid.UUID, set[uuid.UUID]] = {}
    if required_range_type is not None:
        from app.algorithm.types import DutyBlock

        synthetic_block = DutyBlock(
            id=uuid.uuid4(), duty_type_id=shift.duty_type_id, duty_location_id=shift.duty_location_id,
            start_date=shift.start_date, end_date=shift.end_date, score_per_day=Decimal("0"),
            required_range_type=required_range_type,
        )
        weapon_ineligible = bulk_ineligible_duty_blocks(
            session, soldier_ids=[si.id for si in soldier_inputs], duties=[synthetic_block],
            include_alal=True,
        )

    result: list[ShiftCandidateOut] = []
    for si in soldier_inputs:
        if si.id in already_on_shift:
            continue
        exempted = shift.duty_type_id in si.exempted_duty_type_ids
        soldier_node = node_map.get(si.hierarchy_node_id) if si.hierarchy_node_id else None
        soldier_path_ids = list(soldier_node.path_ids) if soldier_node else []
        if not node_in_scope(shift.eligible_node_ids, soldier_path_ids):
            continue
        soldier = soldier_map.get(si.id)
        if soldier is None:
            continue

        has_constraint = any(
            c_start < shift.end_date and c_end >= shift.start_date
            for c_start, c_end in si.approved_constraint_dates
        )
        personal_constraint_warning: PersonalConstraintWarningOut | None = None
        if has_constraint and override_allowed:
            constraint_row = session.execute(
                select(PersonalConstraint).where(
                    PersonalConstraint.soldier_id == si.id,
                    PersonalConstraint.status == "approved",
                    PersonalConstraint.start_date < shift.end_date,
                    PersonalConstraint.end_date >= shift.start_date,
                )
            ).scalars().first()
            if constraint_row is not None:
                decider = session.get(Soldier, constraint_row.decided_by) if constraint_row.decided_by else None
                personal_constraint_warning = PersonalConstraintWarningOut(
                    reason=constraint_row.reason,
                    start_date=constraint_row.start_date,
                    end_date=constraint_row.end_date,
                    decided_by=decider.full_name if decider else None,
                    decided_at=constraint_row.decided_at,
                )
        effective_constraint_block = has_constraint and not override_allowed
        blocked = exempted or effective_constraint_block or si.id in blocked_by_assignment
        blocked_reason: str | None = None
        blocked_detail: str | None = None
        if exempted:
            blocked_reason = "ineligible"
            if si.id in exempted_via_grant:
                blocked_detail = "פטור מסוג תורנות זה"
            elif shift_duty_type is not None:
                blocked_detail = duty_type_ineligibility_reason(
                    soldier, shift_duty_type, mitvahim_months=mitvahim_months, alal_months=alal_months,
                    today=shift.start_date,
                )
        elif effective_constraint_block:
            blocked_reason = "constraint"
        elif si.id in blocked_by_assignment:
            blocked_reason = "assignment"

        burden_share = burden_share_by_id.get(si.id, 0.0)

        weapon_warning = synthetic_block.id in weapon_ineligible.get(si.id, set()) if required_range_type is not None else False

        path_ids = [str(pid) for pid in soldier_path_ids]

        result.append(ShiftCandidateOut(
            soldier_id=si.id,
            full_name=soldier.full_name,
            personal_number=soldier.personal_number,
            burden_share=round(burden_share, 3),
            blocked=blocked,
            blocked_reason=blocked_reason,
            blocked_detail=blocked_detail,
            weapon_warning=weapon_warning,
            hierarchy_path_ids=path_ids,
            personal_constraint_warning=personal_constraint_warning,
        ))

    result.sort(key=lambda x: (x.blocked, x.personal_constraint_warning is not None, x.weapon_warning, x.burden_share))
    return result


class AssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    status: str


@router.get("/{shift_id}/assignments", response_model=list[AssignmentOut])
def list_shift_assignments(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AssignmentOut]:
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    rows = session.execute(
        select(DutyAssignment).where(DutyAssignment.duty_shift_id == shift_id)
    ).scalars().all()
    return [
        AssignmentOut(
            id=a.id,
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
            status=a.status,
        )
        for a in rows
    ]


class BatchAssignRequest(BaseModel):
    primaries: list[uuid.UUID] = Field(default_factory=list)
    reserves: list[uuid.UUID] = Field(default_factory=list)
    override_reason: str | None = Field(default=None, max_length=1000)


class BatchAssignOut(BaseModel):
    primary_assignment_ids: list[uuid.UUID]
    reserve_assignment_ids: list[uuid.UUID]
    reserve_links_created: int


@router.post("/{shift_id}/assign-batch", response_model=BatchAssignOut, status_code=status.HTTP_201_CREATED)
def assign_batch(
    shift_id: uuid.UUID,
    body: BatchAssignRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BatchAssignOut:
    """Create primary + reserve assignments for a shift in one transaction, with automatic DutyReserveLink creation."""
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    if not body.primaries and not body.reserves:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no_soldiers")

    existing_primary_count = session.execute(
        select(func.count()).select_from(DutyAssignment).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.is_reserve == False,  # noqa: E712
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalar_one()
    if existing_primary_count + len(body.primaries) > shift.required_count:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="primary_capacity_exceeded")

    if body.reserves:
        existing_reserve_count = session.execute(
            select(func.count()).select_from(DutyAssignment).where(
                DutyAssignment.duty_shift_id == shift_id,
                DutyAssignment.is_reserve == True,  # noqa: E712
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        ).scalar_one()
        total_reserve_slots = shift.reserve_count_override
        if total_reserve_slots is None:
            from app.services.algorithm_bridge import reserve_count_for_shift
            total_reserve_slots = reserve_count_for_shift(session, shift=shift) or 0
        if existing_reserve_count + len(body.reserves) > total_reserve_slots:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="reserve_capacity_exceeded")

    from app.services import assignments as asvc

    primary_assignments: list[DutyAssignment] = []
    for soldier_id in body.primaries:
        try:
            a = asvc.create_assignment(
                session,
                soldier_id=soldier_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                duty_shift_id=shift.id,
                is_reserve=False,
                actor_id=user.id,
                override_reason=body.override_reason,
            )
            primary_assignments.append(a)
        except asvc.AssignmentError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    reserve_assignments: list[DutyAssignment] = []
    for soldier_id in body.reserves:
        try:
            a = asvc.create_assignment(
                session,
                soldier_id=soldier_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                duty_shift_id=shift.id,
                is_reserve=True,
                actor_id=user.id,
                override_reason=body.override_reason,
            )
            reserve_assignments.append(a)
        except asvc.AssignmentError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Flush so newly created assignments get IDs and are visible to subsequent queries.
    session.flush()

    links_created = 0
    if reserve_assignments:
        # Query ALL active primaries on this shift (includes the ones just flushed above).
        all_primaries = session.execute(
            select(DutyAssignment).where(
                DutyAssignment.duty_shift_id == shift_id,
                DutyAssignment.is_reserve == False,  # noqa: E712
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        ).scalars().all()

        if all_primaries:
            # Skip primaries that already have a reserve link.
            already_linked: set[uuid.UUID] = set(
                session.execute(
                    select(DutyReserveLink.primary_assignment_id).where(
                        DutyReserveLink.primary_assignment_id.in_([a.id for a in all_primaries])
                    )
                ).scalars().all()
            )
            primaries_for_linking = [a for a in all_primaries if a.id not in already_linked]

            if primaries_for_linking:
                hier_parent, hier_children, soldier_node, _ = build_hierarchy_maps(session)
                primary_tuples = [(a.id, a.soldier_id, shift.id) for a in primaries_for_linking]
                reserve_tuples = [(a.id, a.soldier_id, shift.id) for a in reserve_assignments]
                links = link_reserves(
                    primary_assignments=primary_tuples,
                    reserve_assignments=reserve_tuples,
                    soldier_node=soldier_node,
                    hierarchy_parent=hier_parent,
                    hierarchy_children=hier_children,
                )
                for lk in links:
                    session.add(DutyReserveLink(
                        reserve_assignment_id=lk.reserve_assignment_id,
                        primary_assignment_id=lk.primary_assignment_id,
                        hierarchy_distance=lk.hierarchy_distance,
                    ))
                links_created = len(links)

    session.commit()
    return BatchAssignOut(
        primary_assignment_ids=[a.id for a in primary_assignments],
        reserve_assignment_ids=[a.id for a in reserve_assignments],
        reserve_links_created=links_created,
    )


@router.delete("/{shift_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def remove_shift_assignment(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    """Cancel a single assignment that belongs to this shift."""
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    a = session.get(DutyAssignment, assignment_id)
    if a is None or a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if a.status != "cancelled":
        if a.is_reserve:
            session.execute(
                sa_delete(DutyReserveLink).where(DutyReserveLink.reserve_assignment_id == assignment_id)
            )
        else:
            session.execute(
                sa_delete(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == assignment_id)
            )
        before_status = a.status
        a.status = "cancelled"
        write_audit(
            session, actor_id=user.id, action="assignment.cancel", entity_type="duty_assignment",
            entity_id=a.id, before={"status": before_status}, after={"status": "cancelled"},
            context={"source": "shift_assignment_remove"},
        )
        create_notification(
            session, soldier_id=a.soldier_id,
            type=NotificationType.assignment_removed,
            title="שיבוץ בוטל",
            reference_type="duty_assignment", reference_id=a.id,
            actor_id=user.id,
        )
        session.commit()


@router.delete("/{shift_id}/assignments", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def clear_shift_assignments(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    """Remove all non-cancelled assignments linked to this shift."""
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    rows = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status != "cancelled",
        )
    ).scalars().all()
    for a in rows:
        before_status = a.status
        a.status = "cancelled"
        write_audit(
            session, actor_id=user.id, action="assignment.cancel", entity_type="duty_assignment",
            entity_id=a.id, before={"status": before_status}, after={"status": "cancelled"},
            context={"source": "shift_assignments_clear"},
        )
        create_notification(
            session, soldier_id=a.soldier_id,
            type=NotificationType.assignment_removed,
            title="שיבוץ בוטל",
            reference_type="duty_assignment", reference_id=a.id,
            actor_id=user.id,
        )
    session.commit()
