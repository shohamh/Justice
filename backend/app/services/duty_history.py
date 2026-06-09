# backend/app/services/duty_history.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

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


def _fmt(d: Decimal) -> str:
    """Format a Decimal in fixed notation with at least one decimal place.

    Examples: Decimal("3.000") -> "3.0", Decimal("0.600") -> "0.6",
              Decimal("1.300") -> "1.3", Decimal("0.000") -> "0.0"
    """
    n = d.normalize()
    _, _, exponent = n.as_tuple()
    if exponent >= 0:
        return str(int(n)) + ".0"
    return format(n, "f")


def _score_parts(
    a: "DutyAssignment",
    dismissal_ranges: list[tuple[date, date]],
    spd: Decimal,
    standby_mult: Decimal,
    called_up_mult: Decimal,
    dismissed_mult: Decimal,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[str, str]:
    """Return (score_total, score_formula) for the given period of an assignment.

    date_from / date_to optionally restrict computation to a sub-period (used
    for call_up and dismissal events).  score_formula is an empty string when
    there are no days in range or spd is zero.

    Formula notation: "N × SPD × mult" per segment, joined by " + ".
    """
    start = max(a.start_date, date_from) if date_from is not None else a.start_date
    end = min(a.end_date, date_to) if date_to is not None else a.end_date

    if start > end or spd == Decimal("0"):
        return "0.0", ""

    def _day_mult(day: date) -> Decimal:
        if a.is_reserve:
            if (
                a.called_up_from is not None
                and a.called_up_to is not None
                and a.called_up_from <= day <= a.called_up_to
            ):
                return called_up_mult
            return standby_mult
        if any(df <= day <= dt for df, dt in dismissal_ranges):
            return dismissed_mult
        return Decimal("1.0")

    # Group consecutive days by multiplier to build formula segments
    segments: list[tuple[int, Decimal]] = []
    cur_mult: Decimal | None = None
    cur_count = 0

    day = start
    while day <= end:
        m = _day_mult(day)
        if m == cur_mult:
            cur_count += 1
        else:
            if cur_mult is not None:
                segments.append((cur_count, cur_mult))
            cur_mult = m
            cur_count = 1
        day += timedelta(days=1)
    if cur_mult is not None:
        segments.append((cur_count, cur_mult))

    total: Decimal = sum(Decimal(str(count)) * spd * mult for count, mult in segments)
    formula = " + ".join(
        f"{count} × {_fmt(spd)} × {_fmt(mult)}" for count, mult in segments
    )
    return _fmt(total), formula


def _isodate(d: date | None) -> str | None:
    return d.isoformat() if d else None


def get_duty_history(session: Session, soldier_id: uuid.UUID) -> list[TimelineEvent]:
    from app.services.scoring import _get_multiplier_setting

    standby_mult = _get_multiplier_setting(
        session, "scoring.reserve_standby_multiplier", "0.2"
    )
    called_up_mult = _get_multiplier_setting(
        session, "scoring.reserve_called_up_multiplier", "1.3"
    )
    dismissed_mult = _get_multiplier_setting(
        session, "scoring.dismissed_multiplier", "0.0"
    )

    events: list[TimelineEvent] = []

    # --- DutyAssignment events (assignment & cancellation & call_up) ---
    assignments = list(
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.soldier_id == soldier_id,
                DutyAssignment.status.not_in(["algorithm_draft", "algorithm_rejected"]),
            )
        ).scalars().all()
    )

    duty_type_cache: dict[uuid.UUID, str] = {}
    spd_cache: dict[uuid.UUID, Decimal] = {}
    location_cache: dict[uuid.UUID, str] = {}

    def _duty_type_name(dt_id: uuid.UUID) -> str:
        if dt_id not in duty_type_cache:
            dt = session.get(DutyType, dt_id)
            duty_type_cache[dt_id] = dt.name if dt else str(dt_id)
            spd_cache[dt_id] = dt.score_per_day if dt else Decimal("0")
        return duty_type_cache[dt_id]

    def _location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in location_cache:
            loc = session.get(DutyLocation, loc_id)
            location_cache[loc_id] = loc.name if loc else str(loc_id)
        return location_cache[loc_id]

    for a in assignments:
        dt_name = _duty_type_name(a.duty_type_id)
        spd = spd_cache.get(a.duty_type_id, Decimal("0"))
        loc_name = _location_name(a.duty_location_id)

        # Collect dismissals first — needed for score calculation
        dismissals = list(
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id == a.id)
            ).scalars().all()
        )
        dismissal_ranges = [(d.dismissed_from, d.dismissed_to) for d in dismissals]

        # call_up event — if this assignment has called_up_from set
        if a.called_up_from is not None and a.called_up_to is not None:
            cu_total, cu_formula = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=a.called_up_from,
                date_to=a.called_up_to,
            )
            cu_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "is_reserve": "true",
                "score_total": cu_total,
            }
            if cu_formula:
                cu_metadata["score_formula"] = cu_formula
            events.append(
                TimelineEvent(
                    id=uuid.uuid5(a.id, "call_up"),
                    event_type="call_up",
                    date=a.called_up_from.isoformat(),
                    end_date=_isodate(a.called_up_to),
                    title=f"הוקפץ לרזרבה: {dt_name}",
                    description=a.notes,
                    status=None,
                    metadata=cu_metadata,
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
                        "score_total": "0.0",
                    },
                    created_at=a.created_at.isoformat(),
                )
            )
        else:
            asgn_total, asgn_formula = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
            )
            asgn_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "duty_type_id": str(a.duty_type_id),
                "duty_location_id": str(a.duty_location_id),
                "is_reserve": "true" if a.is_reserve else "false",
                "called_up": "true" if a.called_up_from is not None else "false",
                "score_total": asgn_total,
            }
            if asgn_formula:
                asgn_metadata["score_formula"] = asgn_formula
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="assignment",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"{dt_name} ב{loc_name}",
                    description=a.notes,
                    status=a.status,
                    metadata=asgn_metadata,
                    created_at=a.created_at.isoformat(),
                )
            )

        # dismissal events linked to this assignment
        for d in dismissals:
            dis_total, dis_formula = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=d.dismissed_from,
                date_to=d.dismissed_to,
            )
            dis_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "score_total": dis_total,
            }
            if dis_formula:
                dis_metadata["score_formula"] = dis_formula
            events.append(
                TimelineEvent(
                    id=d.id,
                    event_type="dismissal",
                    date=d.dismissed_from.isoformat(),
                    end_date=_isodate(d.dismissed_to),
                    title=f"שוחרר מתורנות {dt_name}",
                    description=d.reason,
                    status=None,
                    metadata=dis_metadata,
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
