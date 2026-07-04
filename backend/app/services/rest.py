from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.duration import combine_date_time
from app.algorithm.rest import last_duty_day
from app.db.models import DutyAssignment, DutyDismissal, DutyType


def resolve_rest_hours(duty_type: DutyType, default_rest_hours: int) -> int:
    """Per-duty-type rest hours override (requirements.rest_hours), or the
    global default."""
    override = (duty_type.requirements or {}).get("rest_hours")
    return int(override) if override is not None else default_rest_hours


def effective_assignment_end(session: Session, assignment: DutyAssignment) -> datetime:
    """The real end of an assignment for rest purposes: the scheduled end, or
    the dismissal moment if the soldier was dismissed through the last duty
    day and never returned to finish the assignment."""
    last_day = last_duty_day(assignment.start_date, assignment.end_date)
    dismissals = session.execute(
        select(DutyDismissal).where(DutyDismissal.duty_assignment_id == assignment.id)
    ).scalars().all()
    permanent = [d for d in dismissals if d.dismissed_to >= last_day]
    if permanent:
        earliest = min(permanent, key=lambda d: d.dismissed_from)
        return combine_date_time(earliest.dismissed_from, assignment.start_time)
    return combine_date_time(last_day, assignment.end_time)


def earliest_eligible_date(effective_end_dt: datetime, rest_hours: int, extra_days: int = 0) -> date:
    """Earliest calendar date on/after which a new duty may start, given
    rest_hours (and any extra_days stacked on top, e.g. gimelim's extra
    rest). Rounds up when the rest window ends mid-day, since callers work
    in whole calendar days."""
    earliest_dt = effective_end_dt + timedelta(hours=rest_hours, days=extra_days)
    if earliest_dt.time() == datetime.min.time():
        return earliest_dt.date()
    return earliest_dt.date() + timedelta(days=1)
