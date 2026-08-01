from __future__ import annotations
import asyncio
import logging
from app.db.session import session_scope
from app.services.range_reminders import send_due_range_reminders
logger = logging.getLogger(__name__)
_POLL_SECONDS = 300

def _send_due_range_reminders() -> None:
    with session_scope() as session:
        count = send_due_range_reminders(session)
        if count:
            logger.info("range reminder worker: sent %d event reminder(s)", count)

async def run_range_reminder_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_send_due_range_reminders)
        except Exception:
            logger.warning("range reminder worker: unhandled error", exc_info=True)
