from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RangeAssignment, RangeAttendanceStatus, RangeEvent, RangeEventStatus
from app.services.ranges import _mitvachim_enabled, mark_attendance


def auto_mark_present_for_elapsed_events(session: Session, *, today: date | None = None) -> int:
    """Auto-marks 'present' every still-pending, non-reserve, non-draft assignment
    on a RangeEvent whose date has already passed. Reuses mark_attendance so
    qualification granting stays consistent with manual marking. Idempotent —
    only ever touches assignments still in the 'pending' state."""
    if not _mitvachim_enabled(session):
        return 0
    today = today or date.today()
    events = session.execute(
        select(RangeEvent).where(
            RangeEvent.date < today,
            RangeEvent.status != RangeEventStatus.cancelled,
        )
    ).scalars().all()
    marked = 0
    for event in events:
        assignments = session.execute(
            select(RangeAssignment).where(
                RangeAssignment.range_event_id == event.id,
                RangeAssignment.attendance_status == RangeAttendanceStatus.pending,
                RangeAssignment.is_reserve.is_(False),
                RangeAssignment.is_draft.is_(False),
            )
        ).scalars().all()
        for assignment in assignments:
            mark_attendance(session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=None)
            marked += 1
    return marked
