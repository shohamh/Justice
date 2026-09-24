from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.services.hr.client import HrApiClient
from app.services.hr.hierarchy_sync import run_hierarchy_sync
from app.services.hr.person_sync import run_person_sync
from app.services.settings_loader import get_setting_int
from app.settings import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_POLL_HOURS = 6

# Arbitrary, stable Postgres advisory-lock key shared between the scheduled
# cron cycle (below) and the admin "run sync now" manual trigger
# (app/routes/hr_review.py), so the two can never run concurrently against
# the same HR data -- a concurrent run could otherwise create duplicate
# conflict rows and per-person IntegrityErrors. Session-scoped (tied to the
# underlying connection), so it must be released before that connection
# returns to the pool.
_SYNC_LOCK_KEY = 0x48525359  # "HRSY"


class SyncAlreadyRunningError(Exception):
    """Raised when the shared advisory lock is already held by another sync
    (the scheduled cron cycle or a concurrent manual trigger)."""


def _try_acquire_sync_lock(session: Session) -> bool:
    return bool(session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _SYNC_LOCK_KEY}).scalar())


def _release_sync_lock(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SYNC_LOCK_KEY})


async def _run_hr_sync_cycle(session: Session) -> None:
    settings = get_settings()
    if not settings.hr_sync_enabled:
        return
    client = HrApiClient(
        settings.hr_api_base_url, settings.hr_api_key,
        ca_bundle_path=settings.hr_api_ca_bundle_path,
        page_size=settings.hr_api_page_size,
    )
    try:
        await run_hierarchy_sync(session, client)
        await run_person_sync(session, client)
    except Exception:
        logger.warning("hr sync worker: unhandled error", exc_info=True)


def _run_hr_sync_cycle_in_own_session() -> int:
    with session_scope() as session:
        poll_hours = get_setting_int(session, "hr_sync.poll_hours", _DEFAULT_POLL_HOURS)
        if not _try_acquire_sync_lock(session):
            # A manual "run sync now" is in flight -- skip this cycle rather
            # than block; the next scheduled wake will try again.
            logger.info("hr sync worker: skipping cycle, sync already running")
            return poll_hours
        try:
            asyncio.run(_run_hr_sync_cycle(session))
            session.commit()
        finally:
            _release_sync_lock(session)
        return poll_hours


def run_sync_now_in_own_session() -> tuple[uuid.UUID, uuid.UUID]:
    """One-shot manual sync (the admin "run sync now" action), run off the
    event loop with its own session and mutually exclusive with the
    scheduled cron cycle via the shared advisory lock. Raises
    SyncAlreadyRunningError if the lock is already held. Caller is
    responsible for checking settings.hr_sync_enabled first."""
    with session_scope() as session:
        if not _try_acquire_sync_lock(session):
            raise SyncAlreadyRunningError("hr sync already running")
        try:
            settings = get_settings()
            client = HrApiClient(
                settings.hr_api_base_url, settings.hr_api_key,
                ca_bundle_path=settings.hr_api_ca_bundle_path,
                page_size=settings.hr_api_page_size,
            )
            hierarchy_run, person_run = asyncio.run(_run_manual_sync(session, client))
            session.commit()
            return hierarchy_run, person_run
        finally:
            _release_sync_lock(session)


async def _run_manual_sync(session: Session, client: HrApiClient) -> tuple[uuid.UUID, uuid.UUID]:
    hierarchy_run = await run_hierarchy_sync(session, client)
    person_run = await run_person_sync(session, client)
    return hierarchy_run.id, person_run.id


async def run_hr_sync_worker() -> None:
    poll_hours = _DEFAULT_POLL_HOURS
    while True:
        await asyncio.sleep(poll_hours * 3600)
        try:
            poll_hours = await asyncio.to_thread(_run_hr_sync_cycle_in_own_session) or _DEFAULT_POLL_HOURS
        except Exception:
            logger.warning("hr sync worker: unhandled error", exc_info=True)
            poll_hours = _DEFAULT_POLL_HOURS
