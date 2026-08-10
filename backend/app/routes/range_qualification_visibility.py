from __future__ import annotations

import uuid
from datetime import date as date_type
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import is_commander, is_duty_manager
from app.auth.deps import require_password_changed
from app.db.models import DutyManagerScope, HierarchyNode, RangeType, Soldier
from app.db.session import get_session
from app.services import ineligible_soldiers as svc

router = APIRouter(prefix="/ranges", tags=["ranges"])

Audience = Literal["planning", "commander"]


class HierarchyNodeOut(BaseModel):
    id: uuid.UUID
    name: str
    level: str
    parent_id: uuid.UUID | None
    path_ids: list[uuid.UUID]


class QualificationSummaryOut(BaseModel):
    range_type: RangeType
    valid_until: date_type


class UpcomingWeaponDutyOut(BaseModel):
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    start_date: date_type
    end_date: date_type
    required_range_type: RangeType
    eligible: bool
    qualification_source: str | None
    covered_by_range_date: date_type | None
    covering_range_type: RangeType | None
    projected_valid_until: date_type | None
    reason: str | None


class UpcomingMatchingRangeOut(BaseModel):
    event_id: uuid.UUID
    range_type: RangeType
    date: date_type


class IneligibleSoldierOut(BaseModel):
    soldier_id: uuid.UUID
    soldier_name: str
    personal_number: str
    hierarchy_node_id: uuid.UUID
    hierarchy_node_name: str
    hierarchy_path_ids: list[uuid.UUID]
    valid_qualifications: list[QualificationSummaryOut]
    has_upcoming_weapon_duty: bool
    has_upcoming_matching_range: bool
    upcoming_weapon_duties: list[UpcomingWeaponDutyOut]
    upcoming_matching_ranges: list[UpcomingMatchingRangeOut]


class IneligibleSoldiersOut(BaseModel):
    count: int
    nodes: list[HierarchyNodeOut]
    soldiers: list[IneligibleSoldierOut]


class IneligibleSoldierCountOut(BaseModel):
    count: int


def _resolve_roots(session: Session, *, user: Soldier, audience: Audience) -> set[uuid.UUID] | None:
    if user.role == "admin":
        return None

    if audience == "planning":
        if not is_duty_manager(session, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return set(
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == user.id
                )
            )
            .scalars()
            .all()
        )

    if not is_commander(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return set(
        session.execute(select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id))
        .scalars()
        .all()
    )


def _visible_path(
    path_ids: tuple[uuid.UUID, ...] | list[uuid.UUID], roots: set[uuid.UUID] | None
) -> list[uuid.UUID]:
    if roots is None:
        return list(path_ids)
    shallowest_root_index = next(
        index for index, node_id in enumerate(path_ids) if node_id in roots
    )
    return list(path_ids[shallowest_root_index:])


def _node_out(
    node: HierarchyNode, *, path_ids: list[uuid.UUID], visible_node_ids: set[uuid.UUID]
) -> HierarchyNodeOut:
    return HierarchyNodeOut(
        id=node.id,
        name=node.name,
        level=node.level,
        parent_id=node.parent_id if node.parent_id in visible_node_ids else None,
        path_ids=path_ids,
    )


def _soldier_out(
    record: svc.IneligibleSoldierRecord,
    *,
    hierarchy_path_ids: list[uuid.UUID],
) -> IneligibleSoldierOut:
    return IneligibleSoldierOut(
        soldier_id=record.soldier_id,
        soldier_name=record.soldier_name,
        personal_number=record.personal_number,
        hierarchy_node_id=record.hierarchy_node_id,
        hierarchy_node_name=record.hierarchy_node_name,
        hierarchy_path_ids=hierarchy_path_ids,
        valid_qualifications=[
            QualificationSummaryOut(
                range_type=qualification.range_type,
                valid_until=qualification.valid_until,
            )
            for qualification in record.valid_qualifications
        ],
        has_upcoming_weapon_duty=record.has_upcoming_weapon_duty,
        has_upcoming_matching_range=record.has_upcoming_matching_range,
        upcoming_weapon_duties=[
            UpcomingWeaponDutyOut(
                assignment_id=duty.assignment_id,
                duty_type_id=duty.duty_type_id,
                duty_type_name=duty.duty_type_name,
                start_date=duty.start_date,
                end_date=duty.end_date,
                required_range_type=duty.required_range_type,
                eligible=record.duty_eligibility[duty.assignment_id].eligible,
                qualification_source=record.duty_eligibility[duty.assignment_id].qualification_source,
                covered_by_range_date=record.duty_eligibility[duty.assignment_id].covered_by_range_date,
                covering_range_type=record.duty_eligibility[duty.assignment_id].covering_range_type,
                projected_valid_until=record.duty_eligibility[duty.assignment_id].projected_valid_until,
                reason=record.duty_eligibility[duty.assignment_id].reason,
            )
            for duty in record.upcoming_weapon_duties
        ],
        upcoming_matching_ranges=[
            UpcomingMatchingRangeOut(
                event_id=range_event.event_id,
                range_type=range_event.range_type,
                date=range_event.date,
            )
            for range_event in record.upcoming_matching_ranges
        ],
    )


def _response(session: Session, *, roots: set[uuid.UUID] | None) -> IneligibleSoldiersOut:
    records = svc.list_ineligible_soldiers(session, roots=roots, as_of=date_type.today())
    record_paths = {
        record.soldier_id: _visible_path(record.hierarchy_path_ids, roots) for record in records
    }
    node_ids = {node_id for path_ids in record_paths.values() for node_id in path_ids}
    nodes_by_id = {
        node.id: node
        for node in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids)))
        .scalars()
        .all()
    }
    nodes = sorted(
        nodes_by_id.values(),
        key=lambda node: (
            tuple(str(node_id) for node_id in node.path_ids),
            node.name,
            str(node.id),
        ),
    )
    return IneligibleSoldiersOut(
        count=len(records),
        nodes=[
            _node_out(
                node,
                path_ids=_visible_path(node.path_ids, roots),
                visible_node_ids=node_ids,
            )
            for node in nodes
        ],
        soldiers=[
            _soldier_out(
                record,
                hierarchy_path_ids=record_paths[record.soldier_id],
            )
            for record in records
        ],
    )


@router.get("/ineligible-soldiers/count", response_model=IneligibleSoldierCountOut)
def get_ineligible_soldier_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> IneligibleSoldierCountOut:
    roots = _resolve_roots(session, user=user, audience="planning")
    records = svc.list_ineligible_soldiers(session, roots=roots, as_of=date_type.today())
    return IneligibleSoldierCountOut(count=len(records))


@router.get("/ineligible-soldiers", response_model=IneligibleSoldiersOut)
def list_ineligible_soldiers(
    audience: Audience,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> IneligibleSoldiersOut:
    roots = _resolve_roots(session, user=user, audience=audience)
    return _response(session, roots=roots)
