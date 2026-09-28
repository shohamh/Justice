"""Queue calendar projection work inside the transaction that changes a source."""

from __future__ import annotations

from datetime import UTC, date, datetime
from heapq import merge
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ExchangeCalendarSyncItem,
    HierarchyNode,
    RangeAssignment,
    RangeEvent,
    RangeLocation,
    Soldier,
)
from app.services.exchange_calendar.outbox import ExchangeCalendarJobPriority, enqueue_source

ISRAEL = ZoneInfo("Asia/Jerusalem")
_MODELS = {"duty_shift": DutyShift, "duty_assignment": DutyAssignment, "range_event": RangeEvent}


def _add_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


def israel_today(now: datetime | None = None) -> date:
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return instant.astimezone(ISRAEL).date()


def _in_window(source: DutyShift | DutyAssignment | RangeEvent, today: date) -> bool:
    start = source.date if isinstance(source, RangeEvent) else source.start_date
    end = source.date if isinstance(source, RangeEvent) else source.end_date
    return end >= today and start <= _add_year(today)


def _already_tracked(session: Session, kind: str, source_id: UUID) -> bool:
    return session.scalar(
        select(ExchangeCalendarSyncItem.id).where(
            ExchangeCalendarSyncItem.source_type == kind,
            ExchangeCalendarSyncItem.source_id == source_id,
        )
    ) is not None


def enqueue_source_change(
    session: Session, kind: str, source_id: UUID, *, reason: str = "user_change",
    today: date | None = None,
) -> bool:
    """Queue a changed official source if eligible or previously synchronized."""
    model = _MODELS[kind]
    source = session.get(model, source_id)
    local_today = today or israel_today()
    if (
        reason != "source_deleted"
        and not _already_tracked(session, kind, source_id)
        and (source is None or not _in_window(source, local_today))
    ):
        return False
    priority = ExchangeCalendarJobPriority.USER_CHANGE
    enqueue_source(session, kind, source_id, priority=priority, reason=reason)
    return True


def enqueue_assignment_change(
    session: Session, assignment: DutyAssignment, *, reason: str = "user_change",
    today: date | None = None,
) -> bool:
    """A shift assignment changes its shared event; a standalone row owns one."""
    if assignment.status not in {"published", "cancelled"}:
        return False
    kind = "duty_shift" if assignment.duty_shift_id else "duty_assignment"
    source_id = assignment.duty_shift_id or assignment.id
    return enqueue_source_change(session, kind, source_id, reason=reason, today=today)


def enqueue_range_change(
    session: Session, event_id: UUID, *, reason: str = "user_change", today: date | None = None,
) -> bool:
    return enqueue_source_change(session, "range_event", event_id, reason=reason, today=today)


def _unique_ids(values):
    return sorted(set(values), key=str)


def enqueue_affected_by_soldier(session: Session, soldier_id: UUID, *, today: date | None = None) -> int:
    """Reproject the soldier's invitations and direct-command subordinates."""
    local_today = today or israel_today()
    subordinate_ids = session.scalars(
        select(Soldier.id).join(HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id).where(
            HierarchyNode.commander_id == soldier_id
        )
    ).all()
    people = _unique_ids([soldier_id, *subordinate_ids])
    source_keys: set[tuple[str, UUID]] = set()
    for assignment in session.scalars(
        select(DutyAssignment).where(
            DutyAssignment.soldier_id.in_(people), DutyAssignment.status == "published"
        )
    ):
        source_keys.add(("duty_shift", assignment.duty_shift_id) if assignment.duty_shift_id else ("duty_assignment", assignment.id))
    range_ids = session.scalars(
        select(RangeAssignment.range_event_id).where(
            RangeAssignment.soldier_id.in_(people), RangeAssignment.is_draft.is_(False)
        )
    ).all()
    source_keys.update(("range_event", value) for value in range_ids)
    manager_ids = session.scalars(
        select(RangeEvent.id).where(RangeEvent.responsible_duty_manager_id == soldier_id)
    ).all()
    source_keys.update(("range_event", value) for value in manager_ids)
    person = session.get(Soldier, soldier_id)
    if person is not None:
        normalized_name = " ".join(person.full_name.split()).casefold()
        for duty_type in session.scalars(select(DutyType).where(DutyType.contact_name.is_not(None))):
            if " ".join(duty_type.contact_name.split()).casefold() == normalized_name:
                source_keys.update(("duty_shift", value) for value in session.scalars(
                    select(DutyShift.id).where(DutyShift.duty_type_id == duty_type.id)
                ))
                source_keys.update(("duty_assignment", value) for value in session.scalars(
                    select(DutyAssignment.id).where(
                        DutyAssignment.duty_type_id == duty_type.id,
                        DutyAssignment.duty_shift_id.is_(None),
                        DutyAssignment.status == "published",
                    )
                ))
        for event in session.scalars(select(RangeEvent).where(RangeEvent.contact_name.is_not(None))):
            if " ".join(event.contact_name.split()).casefold() == normalized_name:
                source_keys.add(("range_event", event.id))
    return sum(
        enqueue_source_change(session, kind, source_id, today=local_today)
        for kind, source_id in sorted(source_keys, key=lambda pair: (pair[0], str(pair[1])))
    )


def enqueue_affected_by_hierarchy_node(session: Session, node_id: UUID, *, today: date | None = None) -> int:
    """Queue invitations for soldiers whose direct commander was reassigned."""
    soldier_ids = session.scalars(select(Soldier.id).where(Soldier.hierarchy_node_id == node_id)).all()
    return sum(enqueue_affected_by_soldier(session, soldier_id, today=today) for soldier_id in soldier_ids)


def enqueue_affected_by_duty_type(session: Session, duty_type_id: UUID, *, today: date | None = None) -> int:
    source_keys = [("duty_shift", value) for value in session.scalars(
        select(DutyShift.id).where(DutyShift.duty_type_id == duty_type_id)
    )]
    source_keys += [("duty_assignment", value) for value in session.scalars(
        select(DutyAssignment.id).where(
            DutyAssignment.duty_type_id == duty_type_id,
            DutyAssignment.duty_shift_id.is_(None),
            DutyAssignment.status == "published",
        )
    )]
    return sum(enqueue_source_change(session, kind, value, today=today) for kind, value in source_keys)


def enqueue_affected_by_location(session: Session, location: DutyLocation | RangeLocation, *, today: date | None = None) -> int:
    if isinstance(location, RangeLocation):
        source_keys = [("range_event", value) for value in session.scalars(
            select(RangeEvent.id).where(RangeEvent.range_location_id == location.id)
        )]
    else:
        source_keys = [("duty_shift", value) for value in session.scalars(
            select(DutyShift.id).where(DutyShift.duty_location_id == location.id)
        )]
        source_keys += [("duty_assignment", value) for value in session.scalars(
            select(DutyAssignment.id).where(
                DutyAssignment.duty_location_id == location.id,
                DutyAssignment.duty_shift_id.is_(None),
                DutyAssignment.status == "published",
            )
        )]
    return sum(enqueue_source_change(session, kind, value, today=today) for kind, value in source_keys)


def bootstrap_calendar_sources(
    session: Session, *, now: datetime | None = None, batch_size: int = 250,
) -> int:
    """Queue eligible official sources in bounded database pages, nearest first."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    today = israel_today(now)
    horizon = _add_year(today)
    sources = (
        ("duty_shift", DutyShift, DutyShift.start_date, DutyShift.end_date, DutyShift.status == "active"),
        ("duty_assignment", DutyAssignment, DutyAssignment.start_date, DutyAssignment.end_date,
         DutyAssignment.status == "published"),
        ("range_event", RangeEvent, RangeEvent.date, RangeEvent.date, RangeEvent.status == "planned"),
    )

    def pages(kind, model, start, end, status_filter):
        offset = 0
        while True:
            query = select(model.id, start).where(start <= horizon, end >= today, status_filter)
            if kind == "duty_assignment":
                query = query.where(DutyAssignment.duty_shift_id.is_(None))
            rows = session.execute(query.order_by(start, model.id).offset(offset).limit(batch_size)).all()
            if not rows:
                return
            for source_id, start_date in rows:
                yield start_date, kind, source_id
            offset += len(rows)

    total = 0
    for _, kind, source_id in merge(*(pages(*source) for source in sources)):
        enqueue_source(session, kind, source_id, priority=ExchangeCalendarJobPriority.BACKFILL, reason="backfill")
        total += 1
    return total
