"""Keep the shared transparency read model current in the background."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from time import perf_counter

from sqlalchemy import text

from app.db.session import session_scope
from app.services import transparency_read_model as model

logger = logging.getLogger(__name__)

_POLL_SECONDS = 10
_LOCK_KEY = "transparency_read_model:refresh"


def _refresh_tick() -> bool:
    """Reuse a current generation or build one, protected across builder commits.

    The advisory lock uses its own session because ``rebuild_generation``
    commits internally. Keeping the lock transaction open on a separate
    session ensures that those commits cannot release the single-flight lock.
    """
    started = perf_counter()
    generation_id: str | None = None
    source_generation: int | None = None
    result = "failed"
    available = False
    try:
        with session_scope() as lock_session:
            acquired = lock_session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": _LOCK_KEY},
            ).scalar_one()
            if not acquired:
                result = "lock_busy"
                return False

            with session_scope() as read_session:
                source_generation, _snapshot = model.capture_source_state(read_session)
                as_of = date.today()
                current = model.current_generation(
                    read_session, source_generation=source_generation, as_of=as_of,
                )
                if current is not None:
                    generation_id = str(current["id"])
                    result = "current"
                    available = True
                else:
                    published = model.rebuild_generation(read_session)
                    if published is not None:
                        generation_id = str(published["id"])
                        source_generation = published["source_generation"]
                        result = "published"
                        available = True
                    else:
                        result = "not_ready"
        return available
    finally:
        logger.info(
            "transparency read model refresh",
            extra={
                "generation_id": generation_id,
                "source_generation": source_generation,
                "result": result,
                "duration_ms": round((perf_counter() - started) * 1000, 1),
            },
        )


async def run_transparency_read_model_worker() -> None:
    """Refresh immediately, then check source freshness every ten seconds."""
    while True:
        try:
            await asyncio.to_thread(_refresh_tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("transparency read model worker: unhandled error", exc_info=True)
        await asyncio.sleep(_POLL_SECONDS)
