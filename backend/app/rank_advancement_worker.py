from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import RankAdvancementInterval, Soldier
from app.db.session import session_scope
from app.services.notifications import notify_rank_advanced, notify_rank_advancement_soon
from app.services.rank_advancement import (
    _career_entry_applies_to_current_rank,
    _career_entry_date,
    compute_next_rank_date,
    get_next_rank,
    resolve_track,
)
from app.services.settings_loader import get_setting_int

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _promote_soldier(session, soldier: Soldier, *, today: date) -> None:
    track = resolve_track(soldier.rank, soldier.rank_track)
    soldier.rank_track = track
    next_rank = get_next_rank(soldier.rank, track=track) if soldier.rank else None
    if next_rank is None:
        soldier.next_rank_date = None
        return
    soldier.rank = next_rank
    soldier.current_rank_since = today
    soldier.next_rank_date_overridden = False
    soldier.next_rank_date = compute_next_rank_date(
        session, rank=next_rank, since=today, track=track
    )
    notify_rank_advanced(session, soldier_id=soldier.id, new_rank=next_rank)


def _promote_on_career_entry(*, today: date | None = None) -> None:
    """Promote at most once for an event on a rank held before career entry.

    The crossing is always recomputed live from mandatory_end_date and
    discharge_date -- never from the stale stored Soldier.is_career cache.
    A rank attained on or after entry cannot reuse the event.
    """
    today = today or date.today()
    with session_scope() as session:
        flagged = session.execute(
            select(RankAdvancementInterval.track, RankAdvancementInterval.rank).where(
                RankAdvancementInterval.advance_on_career_entry.is_(True)
            )
        ).all()
        if not flagged:
            return
        flagged_pairs = set(flagged)
        flagged_ranks = {rank for _track, rank in flagged_pairs}
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.rank.in_(flagged_ranks),
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
            )
        ).scalars().all()
        for s in soldiers:
            if (resolve_track(s.rank, s.rank_track), s.rank) not in flagged_pairs:
                continue
            entry_date = _career_entry_date(s.mandatory_end_date, s.discharge_date)
            if (
                entry_date is not None
                and entry_date <= today
                and _career_entry_applies_to_current_rank(
                    entry_date=entry_date,
                    current_rank_since=s.current_rank_since,
                    enlistment_date=s.enlistment_date,
                )
            ):
                _promote_soldier(session, s, today=today)
        session.commit()


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
            track = resolve_track(s.rank, s.rank_track)
            next_rank = get_next_rank(s.rank, track=track) if s.rank else None
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
            await asyncio.to_thread(_promote_on_career_entry)
            await asyncio.to_thread(_promote_due_soldiers)
            await asyncio.to_thread(_warn_upcoming_soldiers)
        except Exception:
            logger.warning("rank advancement worker: unhandled error", exc_info=True)
