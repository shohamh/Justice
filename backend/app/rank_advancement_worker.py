from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import Soldier
from app.db.session import session_scope
from app.services.notifications import notify_rank_advanced, notify_rank_advancement_soon
from app.services.rank_advancement import compute_next_rank_date, get_next_rank
from app.services.settings_loader import get_setting_int

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _promote_soldier(session, soldier: Soldier, *, today: date) -> None:
    next_rank = get_next_rank(soldier.rank) if soldier.rank else None
    if next_rank is None:
        soldier.next_rank_date = None
        return
    soldier.rank = next_rank
    soldier.current_rank_since = today
    soldier.next_rank_date_overridden = False
    soldier.next_rank_date = compute_next_rank_date(session, rank=next_rank, since=today)
    notify_rank_advanced(session, soldier_id=soldier.id, new_rank=next_rank)


def _promote_due_soldiers() -> None:
    today = date.today()
    with session_scope() as session:
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.next_rank_date.is_not(None),
                Soldier.next_rank_date <= today,
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
            )
        ).scalars().all()
        for s in soldiers:
            _promote_soldier(session, s, today=today)
        session.commit()


def _warn_upcoming_soldiers() -> None:
    today = date.today()
    with session_scope() as session:
        warning_days = get_setting_int(session, "rank_advancement.warning_days", 7)
        target = today + timedelta(days=warning_days)
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.next_rank_date == target,
                # Same discharge/departure filter as _promote_due_soldiers: a
                # soldier who has already left must not get a "promotion coming
                # soon" notification for a promotion that will never happen.
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
            )
        ).scalars().all()
        for s in soldiers:
            next_rank = get_next_rank(s.rank) if s.rank else None
            if next_rank is None:
                continue
            notify_rank_advancement_soon(
                session, soldier_id=s.id, new_rank=next_rank, effective_date=target
            )
        session.commit()


async def run_rank_advancement_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_promote_due_soldiers)
            await asyncio.to_thread(_warn_upcoming_soldiers)
        except Exception:
            logger.warning("rank advancement worker: unhandled error", exc_info=True)
