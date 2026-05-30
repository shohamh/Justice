from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, Soldier

ENLISTED_RANKS = [
    "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
]
OFFICER_RANKS = [
    "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
]
ALL_RANKS = ENLISTED_RANKS + OFFICER_RANKS

SOLDIER_EDITABLE_FIELDS = {"last_mitvahim_date", "last_alal_date", "gender"}


class DutyTypeRequirements(BaseModel):
    allowed_genders: list[str] = []
    requires_mitvahim: bool = False
    requires_alal: bool = False
    allowed_ranks: list[str] = []
    allowed_service_types: list[str] = []
    officers_allowed: bool = True
    enlisted_allowed: bool = True
    requires_bahad1: bool = False


def inferred_service_type(soldier: Soldier, today: date | None = None) -> str | None:
    """Return 'חובה', 'קבע', or None (unknown)."""
    if soldier.mandatory_end_date is None:
        return None
    ref = today or date.today()
    if ref <= soldier.mandatory_end_date:
        return "חובה"
    if soldier.discharge_date is None or soldier.discharge_date > soldier.mandatory_end_date:
        return "קבע"
    return "חובה"


def _is_eligible(soldier: Soldier, reqs: DutyTypeRequirements, *, mitvahim_months: int, alal_months: int, today: date) -> bool:
    """Return False if soldier fails any requirement (fail-safe: null field = blocked if restriction exists)."""
    if reqs.allowed_genders:
        if not soldier.gender or soldier.gender not in reqs.allowed_genders:
            return False

    if reqs.requires_mitvahim:
        if not soldier.last_mitvahim_date:
            return False
        if (today - soldier.last_mitvahim_date) > timedelta(days=mitvahim_months * 30):
            return False

    if reqs.requires_alal:
        if not soldier.last_alal_date:
            return False
        if (today - soldier.last_alal_date) > timedelta(days=alal_months * 30):
            return False

    if reqs.allowed_ranks:
        if not soldier.rank or soldier.rank not in reqs.allowed_ranks:
            return False

    if reqs.allowed_service_types:
        stype = inferred_service_type(soldier, today)
        if not stype or stype not in reqs.allowed_service_types:
            return False

    if not reqs.officers_allowed and soldier.is_officer:
        return False

    if not reqs.enlisted_allowed:
        # blocked if not officer, or if officer status unknown
        if not soldier.is_officer:
            return False

    if reqs.requires_bahad1 and not soldier.bahad1_graduate:
        return False

    return True


def compute_eligibility_exclusions(
    session: Session,
    soldiers: list[Soldier],
    *,
    mitvahim_months: int,
    alal_months: int,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, return the set of duty_type_ids they're ineligible for due to requirements.

    Returns {soldier_id: {duty_type_id, ...}}
    """
    today = date.today()
    duty_types = session.execute(
        select(DutyType).where(DutyType.active.is_(True))
    ).scalars().all()

    exclusions: dict[uuid.UUID, set[uuid.UUID]] = {s.id: set() for s in soldiers}

    for dt in duty_types:
        raw_reqs = dt.requirements or {}
        if not raw_reqs:
            continue
        try:
            reqs = DutyTypeRequirements.model_validate(raw_reqs)
        except Exception:
            continue

        for soldier in soldiers:
            if not _is_eligible(soldier, reqs, mitvahim_months=mitvahim_months, alal_months=alal_months, today=today):
                exclusions[soldier.id].add(dt.id)

    return exclusions
