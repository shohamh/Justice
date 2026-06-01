from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink, Soldier
from app.db.session import get_session
from app.services import reserves as svc

router = APIRouter(tags=["reserves"])


class CallUpRequest(BaseModel):
    from_date: date
    to_date: date


class DismissRequest(BaseModel):
    from_date: date
    to_date: date
    reason: str | None = Field(default=None, max_length=1000)


class ReserveLinkRequest(BaseModel):
    reserve_assignment_id: uuid.UUID


class DismissAndReallocateRequest(BaseModel):
    primary_assignment_id: uuid.UUID
    covering_reserve_assignment_id: uuid.UUID
    from_date: date
    to_date: date
    reason: str | None = Field(default=None, max_length=1000)


class ReallocationOut(BaseModel):
    primary_assignment_id: uuid.UUID
    old_reserve_assignment_id: uuid.UUID
    new_reserve_assignment_id: uuid.UUID | None
    hierarchy_distance: int | None


class DismissalOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    dismissed_from: date
    dismissed_to: date
    reason: str | None
    created_at: datetime


class AssignmentOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    start_date: date
    end_date: date
    status: str


class PrimaryDetailOut(AssignmentOut):
    dismissals: list[DismissalOut]
    reserve_assignment_id: uuid.UUID | None
    reserve_hierarchy_distance: int | None


class ReserveDetailOut(AssignmentOut):
    called_up_from: date | None
    called_up_to: date | None
    primary_assignment_ids: list[uuid.UUID]


class ShiftReserveDetailOut(BaseModel):
    primaries: list[PrimaryDetailOut]
    reserves: list[ReserveDetailOut]


def _load_assignment(session: Session, assignment_id: uuid.UUID) -> DutyAssignment:
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return a


@router.get("/shifts/{shift_id}/reserve-detail", response_model=ShiftReserveDetailOut)
def get_reserve_detail(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftReserveDetailOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    detail = svc.get_shift_reserve_detail(session, shift_id=shift_id)
    primaries = [
        PrimaryDetailOut(
            assignment_id=p["assignment_id"],
            soldier_id=p["soldier_id"],
            start_date=p["start_date"],
            end_date=p["end_date"],
            status=p["status"],
            dismissals=[
                DismissalOut(
                    id=d["id"],
                    duty_assignment_id=p["assignment_id"],
                    dismissed_from=d["from"],
                    dismissed_to=d["to"],
                    reason=d["reason"],
                    created_at=datetime.now(),
                )
                for d in p["dismissals"]
            ],
            reserve_assignment_id=p["reserve_assignment_id"],
            reserve_hierarchy_distance=p["reserve_hierarchy_distance"],
        )
        for p in detail["primaries"]
    ]
    reserves = [
        ReserveDetailOut(
            assignment_id=r["assignment_id"],
            soldier_id=r["soldier_id"],
            start_date=r["start_date"],
            end_date=r["end_date"],
            status=r["status"],
            called_up_from=r["called_up_from"],
            called_up_to=r["called_up_to"],
            primary_assignment_ids=r["primary_assignment_ids"],
        )
        for r in detail["reserves"]
    ]
    return ShiftReserveDetailOut(primaries=primaries, reserves=reserves)


@router.post("/duty-assignments/{assignment_id}/call-up", response_model=dict)
def call_up(
    assignment_id: uuid.UUID,
    body: CallUpRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    a = _load_assignment(session, assignment_id)
    try:
        svc.call_up_reserve(
            session, assignment=a, from_date=body.from_date, to_date=body.to_date, actor_id=user.id
        )
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return {"called_up_from": a.called_up_from, "called_up_to": a.called_up_to}


@router.post(
    "/duty-assignments/{assignment_id}/dismissals",
    response_model=DismissalOut,
    status_code=status.HTTP_201_CREATED,
)
def dismiss(
    assignment_id: uuid.UUID,
    body: DismissRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> DismissalOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    a = _load_assignment(session, assignment_id)
    try:
        d = svc.dismiss_primary(
            session,
            assignment=a,
            from_date=body.from_date,
            to_date=body.to_date,
            reason=body.reason,
            actor_id=user.id,
        )
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(d)
    return DismissalOut(
        id=d.id,
        duty_assignment_id=d.duty_assignment_id,
        dismissed_from=d.dismissed_from,
        dismissed_to=d.dismissed_to,
        reason=d.reason,
        created_at=d.created_at,
    )


@router.delete(
    "/duty-assignments/{assignment_id}/dismissals/{dismissal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_dismissal(
    assignment_id: uuid.UUID,
    dismissal_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    d = session.get(DutyDismissal, dismissal_id)
    if d is None or d.duty_assignment_id != assignment_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.delete_dismissal(session, dismissal=d, actor_id=user.id)
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()


@router.post("/shifts/{shift_id}/dismissals")
def dismiss_and_reallocate(
    shift_id: uuid.UUID,
    body: DismissAndReallocateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)

    primary_a = _load_assignment(session, body.primary_assignment_id)
    if primary_a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_in_shift")

    reserve_a = _load_assignment(session, body.covering_reserve_assignment_id)
    if reserve_a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reserve_not_in_shift")

    try:
        # Step 1: dismiss the primary
        dismissal = svc.dismiss_primary(
            session,
            assignment=primary_a,
            from_date=body.from_date,
            to_date=body.to_date,
            reason=body.reason,
            actor_id=user.id,
        )

        # Step 2: call up the covering reserve
        svc.call_up_reserve(
            session,
            assignment=reserve_a,
            from_date=body.from_date,
            to_date=body.to_date,
            actor_id=user.id,
        )

        # Step 3: relink the dismissed primary to the covering reserve (if different from current)
        current_link = session.execute(
            select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == primary_a.id)
        ).scalar_one_or_none()
        curr_reserve_id = current_link.reserve_assignment_id if current_link else None

        if body.covering_reserve_assignment_id != curr_reserve_id:
            svc.relink_reserve(
                session,
                primary_assignment=primary_a,
                reserve_assignment_id=body.covering_reserve_assignment_id,
                actor_id=user.id,
            )

        # Step 4: reallocate orphaned primaries
        reallocations = svc.reallocate_orphaned_primaries(
            session,
            shift_id=shift_id,
            called_up_reserve_id=reserve_a.id,
            called_up_from=body.from_date,
            called_up_to=body.to_date,
            actor_id=user.id,
        )

    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    session.commit()
    return {
        "dismissal_id": dismissal.id,
        "covering_reserve": {
            "assignment_id": reserve_a.id,
            "called_up_from": body.from_date,
            "called_up_to": body.to_date,
        },
        "reallocations": [
            ReallocationOut(
                primary_assignment_id=r["primary_assignment_id"],
                old_reserve_assignment_id=r["old_reserve_assignment_id"],
                new_reserve_assignment_id=r.get("new_reserve_assignment_id"),
                hierarchy_distance=r.get("hierarchy_distance"),
            )
            for r in reallocations
        ],
    }


@router.put("/shifts/{shift_id}/duty-assignments/{assignment_id}/reserve-link", response_model=dict)
def relink_reserve_route(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: ReserveLinkRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    a = _load_assignment(session, assignment_id)
    if a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_in_shift")
    try:
        link = svc.relink_reserve(
            session,
            primary_assignment=a,
            reserve_assignment_id=body.reserve_assignment_id,
            actor_id=user.id,
        )
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return {
        "reserve_assignment_id": str(link.reserve_assignment_id),
        "hierarchy_distance": link.hierarchy_distance,
    }
