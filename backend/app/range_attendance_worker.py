from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.services.range_attendance_auto_mark import auto_mark_present_for_elapsed_events

logger = logging.getLogger(__name__)
_POLL_SECONDS = 300

def _auto_mark_present_for_elapsed_events() -> None:
    with session_scope() as session:
        count = auto_mark_present_for_elapsed_events(session)
        if count:
            logger.info("range attendance worker: auto-marked %d assignment(s) present", count)

async def run_range_attendance_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_auto_mark_present_for_elapsed_events)
        except Exception:
            logger.warning("range attendance worker: unhandled error", exc_info=True)
