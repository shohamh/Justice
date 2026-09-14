from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import DateTime, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import RangeAssignment, RangeAttendanceStatus, RangeEvent, RangeEventStatus
from app.services.ranges import RangeValidationError, _israel_now_naive, _mitvachim_enabled, mark_attendance

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 30


def auto_mark_present_for_elapsed_events(session: Session, *, now: datetime | None = None) -> int:
    """Auto-marks 'present' every still-pending, non-reserve, non-draft assignment
    on a RangeEvent that has already ended (dated before today, or dated today
    with its own end_time already passed — falls back to waiting for the date
    rollover when no end_time was recorded). Reuses mark_attendance so
    qualification granting stays consistent with manual marking. Idempotent —
    only ever touches assignments still in the 'pending' state.

    Only considers events within the last _LOOKBACK_DAYS days to avoid an
    unbounded historical scan (and, on first deploy, a silent retroactive
    backfill of every past pending assignment ever created)."""
    if not _mitvachim_enabled(session):
        return 0
    now = now or _israel_now_naive()
    today = now.date()
    event_end_at = cast(func.concat(RangeEvent.date, " ", RangeEvent.end_time), DateTime)
    assignments = session.execute(
        select(RangeAssignment)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            or_(
                RangeEvent.date < today,
                and_(
                    RangeEvent.date == today,
                    RangeEvent.end_time.isnot(None),
                    event_end_at <= now,
                ),
            ),
            RangeEvent.date >= today - timedelta(days=_LOOKBACK_DAYS),
            RangeEvent.status != RangeEventStatus.cancelled,
            RangeAssignment.attendance_status == RangeAttendanceStatus.pending,
            RangeAssignment.is_reserve.is_(False),
            RangeAssignment.is_draft.is_(False),
        )
    ).scalars().all()
    marked = 0
    for assignment in assignments:
        try:
            mark_attendance(session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=None)
        except RangeValidationError:
            logger.warning(
                "range attendance auto-mark: skipping assignment %s after validation error",
                assignment.id, exc_info=True,
            )
            continue
        marked += 1
    return marked
