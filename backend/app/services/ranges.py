from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, RangeEvent, RangeEventStatus, RangeType


class RangeValidationError(Exception):
    pass


def create_range_event(
    session: Session,
    *,
    hierarchy_node_id: uuid.UUID,
    range_type: RangeType,
    event_date: date,
    location: str,
    required_count: int,
    reserve_count: int = 0,
    start_time: str | None = None,
    end_time: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> RangeEvent:
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise RangeValidationError("hierarchy_node_not_found")
    if required_count < 0 or reserve_count < 0:
        raise RangeValidationError("counts_must_be_non_negative")

    event = RangeEvent(
        hierarchy_node_id=hierarchy_node_id,
        range_type=range_type,
        date=event_date,
        location=location,
        required_count=required_count,
        reserve_count=reserve_count,
        start_time=start_time,
        end_time=end_time,
        arrival_instructions=arrival_instructions,
        contact_name=contact_name,
        contact_phone=contact_phone,
        notes=notes,
        created_by=created_by,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def update_range_event(
    session: Session,
    *,
    event: RangeEvent,
    location: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    required_count: int | None = None,
    reserve_count: int | None = None,
    notes: str | None = None,
) -> RangeEvent:
    if required_count is not None:
        if required_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        event.required_count = required_count
    if reserve_count is not None:
        if reserve_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        event.reserve_count = reserve_count
    if location is not None:
        event.location = location
    if arrival_instructions is not None:
        event.arrival_instructions = arrival_instructions
    if contact_name is not None:
        event.contact_name = contact_name
    if contact_phone is not None:
        event.contact_phone = contact_phone
    if notes is not None:
        event.notes = notes
    session.commit()
    session.refresh(event)
    return event


def cancel_range_event(session: Session, *, event: RangeEvent) -> RangeEvent:
    event.status = RangeEventStatus.cancelled
    session.commit()
    session.refresh(event)
    return event
