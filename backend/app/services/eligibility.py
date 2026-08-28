from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment, DutyType, ExemptionDutyLocationMap, ExemptionDutyTypeMap, ExemptionType,
    PersonalConstraint, Soldier, SoldierExemption,
)
from app.services.settings_loader import SettingNotFound, get_setting

ENLISTED_RANKS = [
    "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
]
OFFICER_RANKS = [
    "קמא", "סגמ", "סגן", "קאב", "סרן", "קאם", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
]
ALL_RANKS = ENLISTED_RANKS + OFFICER_RANKS

CHOVAH_ONLY_RANKS = ["טוראי", "רבט", "סמל", "סגמ", "קמא"]

RANKS_RASAN_AND_ABOVE = OFFICER_RANKS[OFFICER_RANKS.index("רסן"):]
# ["רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]

SOLDIER_EDITABLE_FIELDS = {
    "last_mitvahim_date", "last_alal_date", "gender", "rank", "rank_track", "phone",
    "military_driving_license", "mandatory_end_date", "discharge_date",
    "food_type", "food_constraints",
}

# Ranks that structurally cannot exist on the other track, confirmed with
# product: קא"ב, סרן, and קא"ם are קבע-only officer ranks (added explicitly
# below, since none of them fall under RANKS_RASAN_AND_ABOVE); סג"ם is always
# חובה (already covered by CHOVAH_ONLY_RANKS). סגן and סמ"ר are deliberately
# unrestricted — סמ"ר is commonly held both by extended-חובה soldiers and by
# קבע soldiers, so it can be either track.
_CHOVAH_ONLY_TRACK_RANKS = frozenset(CHOVAH_ONLY_RANKS)
_KEVA_ONLY_TRACK_RANKS = frozenset(
    [r for r in ENLISTED_RANKS if r not in CHOVAH_ONLY_RANKS and r != "סמר"]
    + list(RANKS_RASAN_AND_ABOVE)
    + ["קאב", "סרן", "קאם"]
)

RANK_TRACK_COMPATIBILITY: dict[str, frozenset[str]] = {
    **{r: frozenset({"חובה"}) for r in _CHOVAH_ONLY_TRACK_RANKS},
    **{r: frozenset({"קבע"}) for r in _KEVA_ONLY_TRACK_RANKS},
}


def validate_rank_track_compatibility(rank: str | None, is_career: bool) -> None:
    """Raise ValueError if rank is structurally incompatible with the given track.

    Ranks with no entry in RANK_TRACK_COMPATIBILITY are unrestricted (can be
    either track) and always pass.
    """
    if rank is None:
        return
    allowed = RANK_TRACK_COMPATIBILITY.get(rank)
    if allowed is None:
        return
    track = "קבע" if is_career else "חובה"
    if track not in allowed:
        raise ValueError(f"rank_track_incompatible: rank {rank!r} is not compatible with track {track!r}")


class DutyTypeRequirements(BaseModel):
    allowed_genders: list[str] = []
    requires_mitvahim: bool = False
    requires_alal: bool = False
    allowed_ranks: list[str] = []
    allowed_service_types: list[str] = []
    # Optional per-rank service-type restriction, for ranks that span both
    # tracks (e.g. סמ"ר, סגן). A rank present here uses this list instead of
    # `allowed_service_types` when checking that soldier; ranks absent from
    # this dict keep using the global `allowed_service_types` filter.
    rank_service_types: dict[str, list[str]] = {}
    officers_allowed: bool = True
    enlisted_allowed: bool = True
    requires_bahad1: bool = False
    requires_military_driving_license: bool = False


def inferred_service_type(soldier: Soldier, today: date | None = None) -> str | None:
    """Return 'חובה', 'קבע', or None (unknown), based on mandatory end date."""
    if soldier.mandatory_end_date is None:
        return None
    ref = today or date.today()
    if ref <= soldier.mandatory_end_date:
        return "חובה"
    return "קבע"


def derive_is_career(
    rank: str | None,
    mandatory_end_date: date | None,
    discharge_date: date | None,
    today: date | None = None,
) -> bool:
    """A soldier is קבע once their mandatory (חובה) service has ended.
    Never true while holding a חובה-only rank, regardless of dates."""
    if rank in CHOVAH_ONLY_RANKS:
        return False
    if mandatory_end_date is None:
        return False
    ref = today or date.today()
    if ref <= mandatory_end_date:
        return False
    return True


BAHAD1_EXCLUDED_OFFICER_RANKS = ["קמא", "קאב", "קאם"]


def derive_bahad1_graduate(rank: str | None) -> bool:
    """Every officer rank is a בה"ד 1 graduate except קמ"א, קא"ב, and קא"ם."""
    if rank not in OFFICER_RANKS:
        return False
    return rank not in BAHAD1_EXCLUDED_OFFICER_RANKS


def _is_eligible(
    soldier: Soldier, reqs: DutyTypeRequirements, *, mitvahim_months: int, alal_months: int, today: date,
    rank_override: str | None = None,
) -> bool:
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

    effective_rank = rank_override if rank_override is not None else soldier.rank

    if reqs.allowed_ranks:
        if not effective_rank or effective_rank not in reqs.allowed_ranks:
            return False

    per_rank_service_types = reqs.rank_service_types.get(effective_rank) if effective_rank else None
    active_service_types = per_rank_service_types if per_rank_service_types is not None else reqs.allowed_service_types
    if active_service_types:
        stype = inferred_service_type(soldier, today)
        if not stype or stype not in active_service_types:
            return False

    if not reqs.officers_allowed and soldier.is_officer:
        return False

    if not reqs.enlisted_allowed:
        # blocked if not officer, or if officer status unknown
        if not soldier.is_officer:
            return False

    if reqs.requires_bahad1 and not soldier.bahad1_graduate:
        return False

    if reqs.requires_military_driving_license:
        if not soldier.has_military_driving_license:
            return False
        if soldier.military_driving_license_expiry and soldier.military_driving_license_expiry < today:
            return False

    return True


def compute_eligibility_exclusions(
    session: Session,
    soldiers: list[Soldier],
    *,
    mitvahim_months: int,
    alal_months: int,
    reference_date: date,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, return the set of duty_type_ids they're ineligible for due to requirements.

    Returns {soldier_id: {duty_type_id, ...}}
    """
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
            if not _is_eligible(soldier, reqs, mitvahim_months=mitvahim_months, alal_months=alal_months, today=reference_date):
                exclusions[soldier.id].add(dt.id)

    return exclusions


def check_soldier_for_assignment(
    session: Session,
    soldier_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    exclude_assignment_id: uuid.UUID | None = None,
    allow_constraint_override: bool = False,
) -> tuple[bool, str | None, dict | None]:
    """Return (True, None, None) if eligible and available.
    Return (False, Hebrew reason, None) if blocked.
    Return (True, None, constraint_warning) if the only issue is an approved
    personal constraint AND allow_constraint_override=True — the caller is
    responsible for collecting an override reason before actually assigning."""
    assignment = session.get(DutyAssignment, assignment_id)
    if assignment is None:
        return False, "שיבוץ לא נמצא", None

    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        return False, "חייל לא נמצא", None

    from app.services.rank_eligibility_projection import project_soldier_state
    projected = project_soldier_state(session, soldier=soldier, as_of=assignment.start_date)
    if projected.departed:
        return False, "החייל סיים שירות עד תאריך זה", None
    today = assignment.start_date

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except (SettingNotFound, ValueError):
            return default

    # 1. Duty type eligibility
    dt = session.get(DutyType, assignment.duty_type_id)
    if dt is not None:
        raw_reqs = dt.requirements or {}
        if raw_reqs:
            try:
                reqs = DutyTypeRequirements.model_validate(raw_reqs)
                mitvahim_months = _setting_int("eligibility.mitvahim_months", 6)
                alal_months = _setting_int("eligibility.alal_months", 3)
                if not _is_eligible(soldier, reqs, mitvahim_months=mitvahim_months,
                                    alal_months=alal_months, today=today, rank_override=projected.rank):
                    return False, "אי-כשירות לסוג תורנות זה", None
            except Exception:
                pass

    # 2. Active exemptions overlapping the duty date range
    exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.start_date < assignment.end_date,
            or_(
                SoldierExemption.end_date.is_(None),
                SoldierExemption.end_date >= assignment.start_date,
            ),
        )
    ).scalars().all()

    for ex in exemptions:
        et = session.get(ExemptionType, ex.exemption_type_id)
        if et and et.is_global:
            return False, "פטור מסוג תורנות זו", None
        dtype_ids = session.execute(
            select(ExemptionDutyTypeMap.duty_type_id).where(
                ExemptionDutyTypeMap.exemption_type_id == ex.exemption_type_id
            )
        ).scalars().all()
        if assignment.duty_type_id in dtype_ids:
            return False, "פטור מסוג תורנות זו", None
        loc_ids = session.execute(
            select(ExemptionDutyLocationMap.duty_location_id).where(
                ExemptionDutyLocationMap.exemption_type_id == ex.exemption_type_id
            )
        ).scalars().all()
        if assignment.duty_location_id in loc_ids:
            return False, "פטור ממיקום תורנות זה", None

    # 3. Approved personal constraint overlapping the duty date range
    constraint_warning: dict | None = None
    constraint = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status == "approved",
            PersonalConstraint.start_date < assignment.end_date,
            PersonalConstraint.end_date >= assignment.start_date,
        )
    ).scalars().first()
    if constraint is not None:
        if not allow_constraint_override:
            return False, "אילוץ אישי מאושר בתאריך זה", None
        decider = session.get(Soldier, constraint.decided_by) if constraint.decided_by else None
        constraint_warning = {
            "reason": constraint.reason,
            "start_date": constraint.start_date,
            "end_date": constraint.end_date,
            "decided_by": decider.full_name if decider else None,
            "decided_at": constraint.decided_at,
        }

    # 4. Scheduling conflict — existing published assignment for this soldier on these dates
    conflict_q = select(DutyAssignment).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status == "published",
        DutyAssignment.start_date < assignment.end_date,
        DutyAssignment.end_date > assignment.start_date,
    )
    if exclude_assignment_id is not None:
        conflict_q = conflict_q.where(DutyAssignment.id != exclude_assignment_id)
    if session.execute(conflict_q).first() is not None:
        return False, "שיבוץ קיים בתאריכים אלו", None

    return True, None, constraint_warning
