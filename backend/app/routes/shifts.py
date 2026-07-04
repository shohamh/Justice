from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_duty_manager_or_admin, require_password_changed
from sqlalchemy import delete as sa_delete, func
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink, DutyShift, DutyType, DutyLocation, HierarchyNode, ShiftTemplate, Soldier, SwapRequest
from app.db.session import get_session
from app.services import shifts as svc
from app.services.algorithm_bridge import build_hierarchy_maps, load_soldier_inputs
from app.services.shift_quotas import ShiftQuotaError, compute_potential_split, get_shift_quotas, set_shift_quotas
from app.algorithm.reserve import link_reserves

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
) -> ShiftOut:
    calculated = None
    if session is not None:
        from app.services.algorithm_bridge import reserve_count_for_shift
        from app.db.models import DutyShift as DutyShiftModel
        shift_obj = session.get(DutyShiftModel, s.id)
        if shift_obj is not None:
            calculated = reserve_count_for_shift(session, shift=shift_obj)
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
    return [_out(s, session, template_name=template_names.get(s.generated_from_template_id) if s.generated_from_template_id else None) for s in shifts]


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


class ShiftCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    personal_number: str
    effort: float
    blocked: bool
    blocked_reason: str | None = None
    hierarchy_path_ids: list[str] = []


@router.get("/{shift_id}/candidates", response_model=list[ShiftCandidateOut])
def get_shift_candidates(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ShiftCandidateOut]:
    """Return eligible soldiers for a shift, sorted by effort ascending. Blocked soldiers (conflict/constraint) appear at end."""
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

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

    soldier_inputs = load_soldier_inputs(session, as_of=shift.start_date)

    result: list[ShiftCandidateOut] = []
    for si in soldier_inputs:
        if si.id in already_on_shift:
            continue
        if shift.duty_type_id in si.exempted_duty_type_ids:
            continue
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
        blocked = has_constraint or si.id in blocked_by_assignment
        blocked_reason: str | None = None
        if has_constraint:
            blocked_reason = "constraint"
        elif si.id in blocked_by_assignment:
            blocked_reason = "assignment"

        effort = float(si.cumulative_score) / float(si.active_days)

        path_ids = [str(pid) for pid in soldier_path_ids]

        result.append(ShiftCandidateOut(
            soldier_id=si.id,
            full_name=soldier.full_name,
            personal_number=soldier.personal_number,
            effort=round(effort, 3),
            blocked=blocked,
            blocked_reason=blocked_reason,
            hierarchy_path_ids=path_ids,
        ))

    result.sort(key=lambda x: (x.blocked, x.effort))
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
    assignment_ids = _assignment_ids_for_shifts(session, shift_ids)

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

    session.commit()
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
    assignment_ids = _assignment_ids_for_shifts(session, shift_ids)

    if assignment_ids:
        session.execute(sa_delete(SwapRequest).where(SwapRequest.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id.in_(assignment_ids) |
            DutyReserveLink.reserve_assignment_id.in_(assignment_ids)
        ))
        session.execute(sa_delete(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids)))

    session.commit()
    return {"cleared_assignments": len(assignment_ids)}


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
        a.status = "cancelled"
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
        a.status = "cancelled"
    session.commit()
