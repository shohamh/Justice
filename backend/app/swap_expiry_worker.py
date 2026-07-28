from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.services.swaps import expire_started_swaps

logger = logging.getLogger(__name__)

_POLL_SECONDS = 300


def _expire_started_swaps() -> None:
    with session_scope() as session:
        count = expire_started_swaps(session)
        if count:
            session.commit()
            logger.info("swap expiry worker: cancelled %d swap request(s) whose duty started", count)


async def run_swap_expiry_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_expire_started_swaps)
        except Exception:
            logger.warning("swap expiry worker: unhandled error", exc_info=True)
