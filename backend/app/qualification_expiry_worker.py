from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import Soldier
from app.db.session import session_scope
from app.services.alal_relevance import is_alal_relevant
from app.services.notifications import (
    notify_alal_expired,
    notify_alal_expiring_soon,
    notify_mitvahim_expired,
    notify_mitvahim_expiring_soon,
)
from app.services.settings_loader import get_setting_int

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _active_soldiers_with_date(session, *, date_column, today: date):
    return session.execute(
        select(Soldier).where(
            date_column.is_not(None),
            Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
            Soldier.left_at.is_(None) | (Soldier.left_at > today),
        )
    ).scalars().all()


def _check_mitvahim_expiry() -> None:
    today = date.today()
    with session_scope() as session:
        validity_days = get_setting_int(session, "home.mitvahim_validity_days", 180)
        warn_days = get_setting_int(session, "home.mitvahim_warn_days", 30)
        soldiers = _active_soldiers_with_date(session, date_column=Soldier.last_mitvahim_date, today=today)
        for s in soldiers:
            expiry = s.last_mitvahim_date + timedelta(days=validity_days)
            if expiry <= today:
                notify_mitvahim_expired(session, soldier_id=s.id, expiry_date=expiry)
            elif expiry <= today + timedelta(days=warn_days):
                notify_mitvahim_expiring_soon(session, soldier_id=s.id, expiry_date=expiry)
        session.commit()


def _check_alal_expiry() -> None:
    today = date.today()
    with session_scope() as session:
        validity_days = get_setting_int(session, "home.alal_validity_days", 90)
        warn_days = get_setting_int(session, "home.alal_warn_days", 30)
        soldiers = _active_soldiers_with_date(session, date_column=Soldier.last_alal_date, today=today)
        for s in soldiers:
            if not is_alal_relevant(session, s):
                continue
            expiry = s.last_alal_date + timedelta(days=validity_days)
            if expiry <= today:
                notify_alal_expired(session, soldier_id=s.id, expiry_date=expiry)
            elif expiry <= today + timedelta(days=warn_days):
                notify_alal_expiring_soon(session, soldier_id=s.id, expiry_date=expiry)
        session.commit()


async def run_qualification_expiry_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_check_mitvahim_expiry)
            await asyncio.to_thread(_check_alal_expiry)
        except Exception:
            logger.warning("qualification expiry worker: unhandled error", exc_info=True)
