# backend/app/services/duty_history.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
)


@dataclass
class TimelineEvent:
    id: uuid.UUID
    event_type: str
    date: str
    end_date: str | None
    title: str
    description: str | None
    status: str | None
    metadata: dict = field(default_factory=dict)
    created_at: str = ""


def _isodate(d: date | None) -> str | None:
    return d.isoformat() if d else None


def get_duty_history(session: Session, soldier_id: uuid.UUID) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    # --- DutyAssignment events (assignment & cancellation & call_up) ---
    assignments = list(
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.soldier_id == soldier_id,
                DutyAssignment.status != "algorithm_draft",
            )
        ).scalars().all()
    )

    duty_type_cache: dict[uuid.UUID, str] = {}
    location_cache: dict[uuid.UUID, str] = {}

    def _duty_type_name(dt_id: uuid.UUID) -> str:
        if dt_id not in duty_type_cache:
            dt = session.get(DutyType, dt_id)
            duty_type_cache[dt_id] = dt.name if dt else str(dt_id)
        return duty_type_cache[dt_id]

    def _location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in location_cache:
            loc = session.get(DutyLocation, loc_id)
            location_cache[loc_id] = loc.name if loc else str(loc_id)
        return location_cache[loc_id]

    for a in assignments:
        dt_name = _duty_type_name(a.duty_type_id)
        loc_name = _location_name(a.duty_location_id)

        # call_up event — if this assignment has called_up_from set
        if a.called_up_from is not None:
            events.append(
                TimelineEvent(
                    id=uuid.uuid5(a.id, "call_up"),
                    event_type="call_up",
                    date=a.called_up_from.isoformat(),
                    end_date=_isodate(a.called_up_to),
                    title=f"הוקפץ לרזרבה: {dt_name}",
                    description=a.notes,
                    status=None,
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                        "is_reserve": "true",
                    },
                    created_at=a.created_at.isoformat(),
                )
            )

        # cancellation or assignment event
        if a.status == "cancelled":
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="cancellation",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"בוטלה: {dt_name} ב{loc_name}",
                    description=a.notes,
                    status="cancelled",
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                        "is_reserve": "true" if a.is_reserve else "false",
                        "called_up": "true" if a.called_up_from is not None else "false",
                    },
                    created_at=a.created_at.isoformat(),
                )
            )
        else:
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="assignment",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"{dt_name} ב{loc_name}",
                    description=a.notes,
                    status=a.status,
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                        "duty_type_id": str(a.duty_type_id),
                        "duty_location_id": str(a.duty_location_id),
                        "is_reserve": "true" if a.is_reserve else "false",
                        "called_up": "true" if a.called_up_from is not None else "false",
                    },
                    created_at=a.created_at.isoformat(),
                )
            )

        # dismissal events linked to this assignment
        dismissals = list(
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id == a.id)
            ).scalars().all()
        )
        for d in dismissals:
            events.append(
                TimelineEvent(
                    id=d.id,
                    event_type="dismissal",
                    date=d.dismissed_from.isoformat(),
                    end_date=_isodate(d.dismissed_to),
                    title=f"שוחרר מתורנות {dt_name}",
                    description=d.reason,
                    status=None,
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                    },
                    created_at=d.created_at.isoformat(),
                )
            )

    # --- ExemptionRequest events ---
    exemption_type_cache: dict[uuid.UUID, str] = {}

    def _exemption_type_name(et_id: uuid.UUID) -> str:
        if et_id not in exemption_type_cache:
            et = session.get(ExemptionType, et_id)
            exemption_type_cache[et_id] = et.name if et else str(et_id)
        return exemption_type_cache[et_id]

    exemption_requests = list(
        session.execute(
            select(ExemptionRequest).where(ExemptionRequest.soldier_id == soldier_id)
        ).scalars().all()
    )
    for er in exemption_requests:
        et_name = _exemption_type_name(er.exemption_type_id)
        events.append(
            TimelineEvent(
                id=er.id,
                event_type="exemption_request",
                date=er.start_date.isoformat(),
                end_date=_isodate(er.end_date),
                title=f"בקשת פטור: {et_name}",
                description=er.reason,
                status=er.status,
                metadata={
                    "exemption_type_name": et_name,
                    "decision_note": er.decision_note,
                },
                created_at=er.created_at.isoformat(),
            )
        )

    # --- PersonalConstraint events ---
    constraints = list(
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.soldier_id == soldier_id)
        ).scalars().all()
    )
    for c in constraints:
        events.append(
            TimelineEvent(
                id=c.id,
                event_type="personal_constraint",
                date=c.start_date.isoformat(),
                end_date=_isodate(c.end_date),
                title="אילוצים אישיים",
                description=c.reason,
                status=c.status,
                metadata={
                    "decision_note": c.decision_note,
                },
                created_at=c.created_at.isoformat(),
            )
        )

    # Sort: descending by date, then by created_at descending
    events.sort(key=lambda e: (e.date, e.created_at), reverse=True)
    return events
