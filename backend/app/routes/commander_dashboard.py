from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import commander_dashboard as svc

router = APIRouter(prefix="/command-dashboard", tags=["command-dashboard"])


class SummaryCards(BaseModel):
    approvals_pending: int
    upcoming_duties_7d: int
    unfilled_gaps: int
    alerts_count: int


class SoldierWithStatus(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    status: str
    cumulative_score: Decimal
    normalised_score: Decimal
    enrolled_at: date
    left_at: date | None


class FairnessStats(BaseModel):
    mean: float
    median: float
    min: float
    max: float
    stddev: float
    soldier_count: int


class NodeFairness(BaseModel):
    node_id: uuid.UUID
    node_name: str
    stats: FairnessStats


class PotentialCount(BaseModel):
    label: str
    count: int
    unit_total: int | None = None


class UpcomingAssignment(BaseModel):
    assignment_id: str
    soldier_id: uuid.UUID
    soldier_name: str
    duty_type_id: str
    duty_type_name: str
    duty_location_id: uuid.UUID
    duty_location_name: str
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    shift_id: uuid.UUID | None
    node_name: str
    is_reserve: bool
    status: str


class UpcomingDay(BaseModel):
    date: date
    assignments: list[UpcomingAssignment]


class Alert(BaseModel):
    severity: str
    soldier_id: uuid.UUID
    soldier_name: str
    message: str


class ApprovalItem(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    request_type: str
    summary: str
    created_at: str


def _get_subtree_ids(session: Session, node_id: uuid.UUID) -> list[uuid.UUID]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return [node_id]
    descendants = (
        session.execute(select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id)))
        .scalars()
        .all()
    )
    return [node_id] + list(descendants)


def _commander_node(session: Session, user: Soldier) -> uuid.UUID | None:
    from app.auth.authz import commanded_node_ids

    # Prefer a node the soldier genuinely commands themselves. A commander
    # who is also an active deputy for another commander must still land on
    # their own dashboard, not have it silently swapped for a deputized one.
    own_ids = (
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id)
        )
        .scalars()
        .all()
    )
    if own_ids:
        return min(own_ids)

    # No direct command of their own — fall back to nodes commanded via an
    # active deputy grant. Pick deterministically (smallest UUID) if several.
    ids = commanded_node_ids(session, user.id)
    return min(ids) if ids else None


def _assert_commander(session: Session, user: Soldier) -> uuid.UUID:
    node_id = _commander_node(session, user)
    if node_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_a_commander")
    authorize(session, user, Action.HIERARCHY_READ, target_node=session.get(HierarchyNode, node_id))
    return node_id


@router.get("/summary", response_model=SummaryCards)
def get_summary(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SummaryCards:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.summary_cards(session, subtree_ids=subtree)


@router.get("/soldiers", response_model=list[SoldierWithStatus])
def get_soldiers(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SoldierWithStatus]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.soldiers_in_subtree(session, subtree_ids=subtree)


@router.get("/fairness/internal", response_model=FairnessStats)
def fairness_internal(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FairnessStats:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.fairness_stats(session, subtree_ids=subtree)


@router.get("/fairness/external", response_model=list[NodeFairness])
def fairness_external(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NodeFairness]:
    node_id = _assert_commander(session, user)
    node = session.get(HierarchyNode, node_id)
    if node is None or node.parent_id is None:
        return []
    siblings = (
        session.execute(
            select(HierarchyNode).where(
                HierarchyNode.parent_id == node.parent_id,
                HierarchyNode.id != node_id,
            )
        )
        .scalars()
        .all()
    )
    result: list[NodeFairness] = []
    node_subtree = _get_subtree_ids(session, node_id)
    result.append(
        NodeFairness(
            node_id=node_id,
            node_name=node.name,
            stats=svc.fairness_stats(session, subtree_ids=node_subtree),
        )
    )
    for sibling in siblings:
        sib_subtree = _get_subtree_ids(session, sibling.id)
        result.append(
            NodeFairness(
                node_id=sibling.id,
                node_name=sibling.name,
                stats=svc.fairness_stats(session, subtree_ids=sib_subtree),
            )
        )
    return result


@router.get("/potential", response_model=list[PotentialCount])
def potential(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[PotentialCount]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.potential_counts(session, subtree_ids=subtree)


@router.get("/upcoming", response_model=list[UpcomingDay])
def upcoming(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[UpcomingDay]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.upcoming_duties(session, subtree_ids=subtree, days=None)


@router.get("/alerts", response_model=list[Alert])
def alerts(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[Alert]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.alerts(session, subtree_ids=subtree)


@router.get("/approvals", response_model=list[ApprovalItem])
def approvals(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ApprovalItem]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.pending_approvals(session, subtree_ids=subtree)
