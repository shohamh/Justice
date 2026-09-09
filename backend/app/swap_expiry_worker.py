from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.services.exemption_requests import expire_stale_exemption_requests
from app.services.swaps import expire_started_swaps

logger = logging.getLogger(__name__)

_POLL_SECONDS = 300


def _expire_stale_requests() -> None:
    with session_scope() as session:
        swap_count = expire_started_swaps(session)
        exemption_count = expire_stale_exemption_requests(session)
        if swap_count or exemption_count:
            session.commit()
            logger.info(
                "expiry worker: cancelled %d swap request(s), expired %d exemption request(s)",
                swap_count, exemption_count,
            )


async def run_swap_expiry_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_expire_stale_requests)
        except Exception:
            logger.warning("expiry worker: unhandled error", exc_info=True)
