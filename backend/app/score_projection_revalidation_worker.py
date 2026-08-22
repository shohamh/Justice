from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.services.score_projection_reconciliation import revalidate_score_projection

logger = logging.getLogger(__name__)

_POLL_SECONDS = 3600
_BATCH_SIZE = 2000


def _revalidate_tick() -> None:
    with session_scope() as session:
        stats = revalidate_score_projection(session, batch_size=_BATCH_SIZE)
        if stats["validated"] or stats["violations"]:
            logger.info(
                "score projection revalidation: validated=%(validated)d violations=%(violations)d repaired=%(repaired)d",
                stats,
            )
        session.commit()


async def run_score_projection_revalidation_worker() -> None:
    """Periodically fingerprint-proof score-projection buckets.

    Reads trust the writer invariant and skip the per-bucket JSONB proof; this
    worker is the counterpart that still runs the proof over every bucket,
    cycling through the table in keyset order a batch at a time, so corrupted
    or interrupted writes are eventually detected and rebuilt from canonical
    rows.
    """
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_revalidate_tick)
        except Exception:
            logger.warning("score projection revalidation worker: unhandled error", exc_info=True)
