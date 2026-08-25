"""Soldier-facing "my requests" endpoints.

Backs the requests page: per-request-type history views scoped to the
authenticated soldier, plus the unseen-decision counter / mark-seen pair that
drives the existing-requests tab badge.

Two request types carry no decision timestamp column, so their decision moment
is derived from rows written at decision time:
- ExemptionRequest → the approval/rejection Notification sent to the requester.
- HierarchyTransferRequest → the approve/reject AuditLog entry.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import (
    AuditLog,
    ExemptionRequest,
    HierarchyNode,
    HierarchyTransferRequest,
    Notification,
    NotificationType,
    PersonalConstraint,
    RangeAssignment,
    RangeExcusalRequest,
    RangeEvent,
    RangeLocation,
    Soldier,
    SoldierEnrollmentRequest,
    SoldierFieldUpdate,
    SwapRequest,
)
from app.db.session import get_session
from app.services.settings_loader import SettingNotFound, get_setting, set_setting

router = APIRouter(prefix="/me", tags=["me"])

# Per-soldier KV key (system_settings) storing the last requests-page visit.
_LAST_SEEN_KEY = "requests_last_seen:{soldier_id}"

_TRANSFER_DECISION_ACTIONS = ("hierarchy_transfer.approve", "hierarchy_transfer.reject")
_DECIDED_EXEMPTION_NOTIFICATION_TYPES = (
    NotificationType.exemption_approved,
    NotificationType.exemption_rejected,
)


# ── Schemas ──


class NodeRefOut(BaseModel):
    id: uuid.UUID
    name: str


class HierarchyTransferOut(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    from_node: NodeRefOut | None
    to_node: NodeRefOut | None


class EnrollmentRequestOut(BaseModel):
    id: uuid.UUID
    status: str
    requested_node_id: uuid.UUID
    requested_node_name: str | None
    created_at: datetime
    decided_at: datetime | None
    decision_note: str | None


class EnrollmentOut(BaseModel):
    request: EnrollmentRequestOut | None


class RangeExcusalOut(BaseModel):
    id: uuid.UUID
    status: str
    reason: str
    # RangeExcusalRequest stores this as requested_at; exposed under the same
    # created_at name every other request type uses.
    created_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    range_date: date | None
    range_type: str | None
    range_location_name: str | None


class UnseenCountOut(BaseModel):
    count: int


# ── Helpers ──


def _range_location_names(session: Session, location_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not location_ids:
        return {}
    rows = session.execute(select(RangeLocation).where(RangeLocation.id.in_(location_ids))).scalars()
    return {loc.id: loc.name for loc in rows}


def _plain(value: object) -> object:
    """Unwrap str-enum members so responses carry bare strings."""
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _last_seen_key(soldier_id: uuid.UUID) -> str:
    return _LAST_SEEN_KEY.format(soldier_id=soldier_id)


def _last_seen(session: Session, soldier_id: uuid.UUID) -> datetime | None:
    try:
        raw = get_setting(session, _last_seen_key(soldier_id))
    except SettingNotFound:
        return None
    parsed = raw if isinstance(raw, datetime) else None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _node_names(session: Session, node_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not node_ids:
        return {}
    rows = session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))).scalars()
    return {n.id: n.name for n in rows}


def _transfer_decision_times(session: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    rows = session.execute(
        select(AuditLog.entity_id, func.max(AuditLog.created_at))
        .where(
            AuditLog.entity_type == "hierarchy_transfer_request",
            AuditLog.action.in_(_TRANSFER_DECISION_ACTIONS),
            AuditLog.entity_id.in_(request_ids),
        )
        .group_by(AuditLog.entity_id)
    ).all()
    return {entity_id: ts for entity_id, ts in rows}


# ── History views ──


@router.get("/hierarchy-transfers", response_model=list[HierarchyTransferOut])
def my_hierarchy_transfers(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[HierarchyTransferOut]:
    reqs = list(
        session.execute(
            select(HierarchyTransferRequest)
            .where(HierarchyTransferRequest.soldier_id == user.id)
            .order_by(HierarchyTransferRequest.created_at.desc(), HierarchyTransferRequest.id)
        ).scalars()
    )
    if not reqs:
        return []

    decided_at = _transfer_decision_times(session, [r.id for r in reqs])
    names = _node_names(
        session,
        {r.to_node_id for r in reqs} | {r.from_node_id for r in reqs if r.from_node_id is not None},
    )

    def _node(node_id: uuid.UUID | None) -> NodeRefOut | None:
        if node_id is None:
            return None
        return NodeRefOut(id=node_id, name=names.get(node_id, ""))

    return [
        HierarchyTransferOut(
            id=r.id,
            status=r.status,
            created_at=r.created_at,
            decided_at=decided_at.get(r.id),
            decision_note=r.decision_note,
            from_node=_node(r.from_node_id),
            to_node=_node(r.to_node_id),
        )
        for r in reqs
    ]


@router.get("/enrollment", response_model=EnrollmentOut)
def my_enrollment(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EnrollmentOut:
    req = session.execute(
        select(SoldierEnrollmentRequest)
        .where(SoldierEnrollmentRequest.soldier_id == user.id)
        .order_by(SoldierEnrollmentRequest.created_at.desc(), SoldierEnrollmentRequest.id)
        .limit(1)
    ).scalar_one_or_none()
    if req is None:
        return EnrollmentOut(request=None)
    node = session.get(HierarchyNode, req.requested_node_id)
    return EnrollmentOut(
        request=EnrollmentRequestOut(
            id=req.id,
            status=req.status,
            requested_node_id=req.requested_node_id,
            requested_node_name=node.name if node else None,
            created_at=req.created_at,
            decided_at=req.decided_at,
            decision_note=req.decision_note,
        )
    )


@router.get("/range-excusal-requests", response_model=list[RangeExcusalOut])
def my_range_excusal_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeExcusalOut]:
    reqs = list(
        session.execute(
            select(RangeExcusalRequest)
            .where(RangeExcusalRequest.requested_by == user.id)
            .order_by(RangeExcusalRequest.requested_at.desc())
        ).scalars()
    )
    if not reqs:
        return []

    # Resolve the range each request was for. Prefer range_event_id (it
    # survives approved excusals deleting the assignment); fall back through
    # the assignment while it still exists.
    event_ids: set[uuid.UUID] = {r.range_event_id for r in reqs if r.range_event_id is not None}
    fallback_assignment_ids = {
        r.range_assignment_id
        for r in reqs
        if r.range_event_id is None and r.range_assignment_id is not None
    }
    assignments_by_id: dict[uuid.UUID, RangeAssignment] = {}
    if fallback_assignment_ids:
        assignments_by_id = {
            a.id: a
            for a in session.execute(
                select(RangeAssignment).where(RangeAssignment.id.in_(fallback_assignment_ids))
            ).scalars()
        }
        event_ids.update(a.range_event_id for a in assignments_by_id.values())

    events_by_id: dict[uuid.UUID, RangeEvent] = {}
    if event_ids:
        events_by_id = {
            e.id: e for e in session.execute(select(RangeEvent).where(RangeEvent.id.in_(event_ids))).scalars()
        }
    location_names = _range_location_names(
        session, {e.range_location_id for e in events_by_id.values()}
    )
    out: list[RangeExcusalOut] = []
    for r in reqs:
        event: RangeEvent | None = None
        if r.range_event_id is not None:
            event = events_by_id.get(r.range_event_id)
        elif r.range_assignment_id is not None:
            assignment = assignments_by_id.get(r.range_assignment_id)
            event = events_by_id.get(assignment.range_event_id) if assignment else None
        out.append(
            RangeExcusalOut(
                id=r.id,
                status=str(_plain(r.status)),
                reason=r.reason,
                created_at=r.requested_at,
                decided_at=r.decided_at,
                decision_note=r.decision_note,
                range_date=event.date if event else None,
                range_type=str(_plain(event.range_type)) if event else None,
                range_location_name=location_names.get(event.range_location_id) if event else None,
            )
        )
    return out


# ── Unseen badge ──


def _count_unseen_decisions(session: Session, soldier_id: uuid.UUID, last_seen: datetime) -> int:
    total = 0

    total += session.execute(
        select(func.count())
        .select_from(PersonalConstraint)
        .where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.decided_at.is_not(None),
            PersonalConstraint.decided_at > last_seen,
        )
    ).scalar_one()

    # ExemptionRequest has no decided_at column; its decision instant is the
    # approval/rejection notification written to the requester.
    total += session.execute(
        select(func.count())
        .select_from(ExemptionRequest)
        .join(
            Notification,
            (Notification.reference_id == ExemptionRequest.id)
            & (Notification.soldier_id == ExemptionRequest.soldier_id)
            & (Notification.reference_type == "exemption_request")
            & Notification.type.in_(_DECIDED_EXEMPTION_NOTIFICATION_TYPES)
            & (Notification.created_at > last_seen),
        )
        .where(
            ExemptionRequest.soldier_id == soldier_id,
            ExemptionRequest.status.in_(["approved", "rejected"]),
        )
    ).scalar_one()

    total += session.execute(
        select(func.count())
        .select_from(SoldierFieldUpdate)
        .where(
            SoldierFieldUpdate.soldier_id == soldier_id,
            SoldierFieldUpdate.decided_at.is_not(None),
            SoldierFieldUpdate.decided_at > last_seen,
        )
    ).scalar_one()

    total += session.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.entity_type == "hierarchy_transfer_request",
            AuditLog.action.in_(_TRANSFER_DECISION_ACTIONS),
            AuditLog.entity_id.in_(
                select(HierarchyTransferRequest.id).where(HierarchyTransferRequest.soldier_id == soldier_id)
            ),
            AuditLog.created_at > last_seen,
        )
    ).scalar_one()

    total += session.execute(
        select(func.count())
        .select_from(SoldierEnrollmentRequest)
        .where(
            SoldierEnrollmentRequest.soldier_id == soldier_id,
            SoldierEnrollmentRequest.decided_at.is_not(None),
            SoldierEnrollmentRequest.decided_at > last_seen,
        )
    ).scalar_one()

    total += session.execute(
        select(func.count())
        .select_from(RangeExcusalRequest)
        .where(
            RangeExcusalRequest.requested_by == soldier_id,
            RangeExcusalRequest.decided_at.is_not(None),
            RangeExcusalRequest.decided_at > last_seen,
        )
    ).scalar_one()

    total += session.execute(
        select(func.count())
        .select_from(SwapRequest)
        .where(
            SwapRequest.requesting_soldier_id == soldier_id,
            SwapRequest.updated_at > last_seen,
            SwapRequest.status.in_(["open", "applied", "rejected"]),
        )
    ).scalar_one()

    return int(total)


@router.get("/requests/unseen-count", response_model=UnseenCountOut)
def unseen_request_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnseenCountOut:
    last_seen = _last_seen(session, user.id)
    if last_seen is None:
        return UnseenCountOut(count=0)
    return UnseenCountOut(count=_count_unseen_decisions(session, user.id, last_seen))


@router.post("/requests/mark-seen", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def mark_requests_seen(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    set_setting(
        session,
        _last_seen_key(user.id),
        datetime.now(timezone.utc).isoformat(),
        actor_id=user.id,
    )
    session.commit()
