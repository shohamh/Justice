from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.services.range_attendance_auto_mark import auto_mark_present_for_elapsed_events
from app.services.ranges import mark_past_range_events_completed

logger = logging.getLogger(__name__)
_POLL_SECONDS = 300

def _auto_mark_present_for_elapsed_events() -> None:
    with session_scope() as session:
        completed_count = mark_past_range_events_completed(session)
        attendance_count = auto_mark_present_for_elapsed_events(session)
        session.commit()
        if completed_count:
            logger.info("range attendance worker: completed %d elapsed range event(s)", completed_count)
        if attendance_count:
            logger.info("range attendance worker: auto-marked %d assignment(s) present", attendance_count)

async def run_range_attendance_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_auto_mark_present_for_elapsed_events)
        except Exception:
            logger.warning("range attendance worker: unhandled error", exc_info=True)
