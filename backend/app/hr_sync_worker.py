from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.services.hr.client import HrApiClient
from app.services.hr.hierarchy_sync import run_hierarchy_sync
from app.services.hr.person_sync import run_person_sync
from app.services.settings_loader import get_setting_int
from app.settings import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_POLL_HOURS = 6


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
        asyncio.run(_run_hr_sync_cycle(session))
        session.commit()
        return poll_hours


async def run_hr_sync_worker() -> None:
    poll_hours = _DEFAULT_POLL_HOURS
    while True:
        await asyncio.sleep(poll_hours * 3600)
        try:
            poll_hours = await asyncio.to_thread(_run_hr_sync_cycle_in_own_session) or _DEFAULT_POLL_HOURS
        except Exception:
            logger.warning("hr sync worker: unhandled error", exc_info=True)
            poll_hours = _DEFAULT_POLL_HOURS
