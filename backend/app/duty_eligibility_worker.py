from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.models import DutyAssignment, DutyType
from app.db.session import session_scope
from app.services.duty_eligibility_watch import recheck_assignments

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _recheck_all_published_weapon_assignments() -> None:
    with session_scope() as session:
        weapon_type_ids = session.execute(
            select(DutyType.id).where(DutyType.required_range_type.is_not(None))
        ).scalars().all()
        if not weapon_type_ids:
            return
        assignment_ids = session.execute(
            select(DutyAssignment.id).where(
                DutyAssignment.duty_type_id.in_(weapon_type_ids),
                DutyAssignment.status == "published",
            )
        ).scalars().all()
        if not assignment_ids:
            return
        count = recheck_assignments(session, assignment_ids)
        if count:
            logger.info("duty eligibility worker: %d assignment(s) newly weapon-ineligible", count)


async def run_duty_eligibility_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_recheck_all_published_weapon_assignments)
        except Exception:
            logger.warning("duty eligibility worker: unhandled error", exc_info=True)
