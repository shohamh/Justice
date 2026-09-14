from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import ScoreProjectionState
from app.db.session import session_scope
from app.services.score_projection import SCORE_PROJECTION_STATE_KEY, backfill_score_projection
from app.services.score_projection_reconciliation import revalidate_score_projection

logger = logging.getLogger(__name__)

_POLL_SECONDS = 3600
_BACKFILL_POLL_SECONDS = 10
_BATCH_SIZE = 2000
_LOCK_KEY = "justice.score_projection_maintenance"


def _projection_tick(session: Session) -> bool:
    """Run one exclusive maintenance batch and return whether it is complete."""
    acquired = session.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": _LOCK_KEY},
    ).scalar()
    if not acquired:
        return False

    state = session.get(ScoreProjectionState, SCORE_PROJECTION_STATE_KEY)
    if state is None or not state.backfill_complete:
        state = backfill_score_projection(session, batch_size=_BATCH_SIZE)
        logger.info(
            "score projection backfill progress: complete=%s resume_after_quarter=%s",
            state.backfill_complete,
            state.resume_after_quarter_start,
        )
        session.commit()
        return state.backfill_complete

    stats = revalidate_score_projection(session, batch_size=_BATCH_SIZE)
    if stats["validated"] or stats["violations"]:
        logger.info(
            "score projection revalidation: validated=%(validated)d violations=%(violations)d repaired=%(repaired)d",
            stats,
        )
    session.commit()
    return True


def _maintenance_tick() -> bool:
    with session_scope() as session:
        return _projection_tick(session)


async def run_score_projection_revalidation_worker() -> None:
    """Self-heal score projections, then periodically fingerprint-proof them.

    An interrupted initial backfill is resumed immediately in bounded batches.
    While it is incomplete, the worker retries frequently; after completion it
    switches to hourly validation. Each batch uses a transaction-scoped
    advisory lock so multiple application processes do not duplicate work.
    """
    complete = False
    while True:
        try:
            complete = await asyncio.to_thread(_maintenance_tick)
        except Exception:
            logger.warning("score projection revalidation worker: unhandled error", exc_info=True)
            complete = False
        await asyncio.sleep(_POLL_SECONDS if complete else _BACKFILL_POLL_SECONDS)
