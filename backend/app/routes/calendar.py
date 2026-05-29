from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyLocation, DutyType, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as scoring_svc

router = APIRouter(prefix="/calendar", tags=["calendar"])


class CalAssignment(BaseModel):
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    duty_type_name: str
    duty_location_name: str
    duty_type_color: str


class CalRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    assignments: list[CalAssignment]


def _duty_type_color(duty_type_id: uuid.UUID) -> str:
    h = hash(duty_type_id) % 360
    return f"hsl({h}, 65%, 50%)"


@router.get("/unit", response_model=list[CalRow])
def unit_calendar(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[CalRow]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_READ, target_node=node)
    subtree_node_ids = (
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id))  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )
    soldiers = (
        session.execute(
            select(Soldier).where(
                Soldier.hierarchy_node_id.in_(subtree_node_ids), Soldier.left_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    soldier_ids = [s.id for s in soldiers]
    duty_types = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    duty_locations = {dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()}
    spans = scoring_svc.effective_duty_spans(
        session, soldier_ids=set(soldier_ids), date_from=date_from, date_to=date_to
    )
    by_soldier: dict[uuid.UUID, list[CalAssignment]] = {sid: [] for sid in soldier_ids}
    for sp in spans:
        dt_id = sp["duty_type_id"]
        dl_id = sp["duty_location_id"]
        by_soldier[sp["soldier_id"]].append(
            CalAssignment(
                assignment_id=sp["assignment_id"],
                duty_type_id=dt_id,
                duty_location_id=dl_id,
                start_date=sp["start_date"],
                end_date=sp["end_date"],
                duty_type_name=duty_types.get(dt_id, ""),
                duty_location_name=duty_locations.get(dl_id, ""),
                duty_type_color=_duty_type_color(dt_id),
            )
        )
    return [
        CalRow(soldier_id=s.id, full_name=s.full_name, assignments=by_soldier[s.id])
        for s in soldiers
    ]
