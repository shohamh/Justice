from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS, derive_is_career
from app.services.hr.schemas import HrUser

# Confirmed against real HR API responses: gender comes back as a bare "M"/"F".
GENDER_MAP: dict[str, str] = {
    "M": "male",
    "F": "female",
}

# Keys are HR's raw `rank` string; values are Justice's existing rank
# strings from eligibility.ENLISTED_RANKS / OFFICER_RANKS. Identity-shaped
# today because no real HR fixture data is available to confirm otherwise
# — if HR uses different rank spellings/abbreviations, this map is where
# that translation goes, one confirmed entry at a time.
RANK_MAP: dict[str, str] = {rank: rank for rank in (*ENLISTED_RANKS, *OFFICER_RANKS)}

# HR's `serviceType` -> Soldier.rank_track. Confirmed against real HR API
# responses: the raw value IS the Hebrew word itself ("חובה" mandatory /
# "קבע" career), not an English transliteration — identity-shaped like
# RANK_MAP, kept as an explicit dict (not a passthrough) so an unexpected
# third value still lands in held-for-review instead of being silently
# accepted.
SERVICE_TYPE_TO_TRACK_MAP: dict[str, str] = {
    "חובה": "חובה",
    "קבע": "קבע",
}

HR_OWNED_FIELDS: frozenset[str] = frozenset({
    "full_name", "personal_number", "email", "phone", "gender", "rank", "rank_track",
    "profile_picture_url", "enlistment_date", "mandatory_end_date", "discharge_date",
})


@dataclass(frozen=True)
class MappedSoldierFields:
    full_name: str
    personal_number: str
    email: str | None = None
    phone: str | None = None
    profile_picture_url: str | None = None
    gender: str | None = None
    rank: str | None = None
    rank_track: str | None = None
    is_officer: bool = False
    is_career: bool = False
    enlistment_date: date | None = None
    mandatory_end_date: date | None = None
    discharge_date: date | None = None


@dataclass(frozen=True)
class HeldForReview:
    personal_number: str
    reasons: list[str] = field(default_factory=list)


def _parse_date(value: str | None, field_label: str, reasons: list[str]) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    # HR's date fields are confirmed to sometimes come back as a full ISO
    # datetime ("...T...", e.g. with a midnight time component and/or a
    # timezone offset) rather than a bare date — date.fromisoformat rejects
    # that outright, so fall back to parsing it as a datetime and taking
    # just the date part.
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        reasons.append(f"unparseable {field_label}: {value!r}")
        return None


def map_hr_user(hr_user: HrUser) -> MappedSoldierFields | HeldForReview:
    reasons: list[str] = []

    mapped_gender: str | None = None
    if hr_user.gender is not None:
        mapped_gender = GENDER_MAP.get(hr_user.gender)
        if mapped_gender is None:
            reasons.append(f"unmappable gender: {hr_user.gender!r}")

    mapped_rank: str | None = None
    if hr_user.rank is not None:
        mapped_rank = RANK_MAP.get(hr_user.rank)
        if mapped_rank is None:
            reasons.append(f"unmappable rank: {hr_user.rank!r}")

    mapped_track: str | None = None
    if hr_user.serv_type is not None:
        mapped_track = SERVICE_TYPE_TO_TRACK_MAP.get(hr_user.serv_type)
        if mapped_track is None:
            reasons.append(f"unmappable serviceType: {hr_user.serv_type!r}")

    enlistment_date = _parse_date(hr_user.service_start_date, "serviceStartDate", reasons)
    mandatory_end_date = _parse_date(hr_user.end_hova_date, "endHovaDate", reasons)
    discharge_date = _parse_date(hr_user.service_end_date, "serviceEndDate", reasons)

    if not hr_user.personal_number:
        reasons.append("missing personal_number")
    if not hr_user.full_name:
        reasons.append("missing full_name")

    if reasons:
        return HeldForReview(personal_number=hr_user.personal_number or "", reasons=reasons)

    is_officer = mapped_rank in OFFICER_RANKS if mapped_rank else False
    is_career = derive_is_career(mapped_rank, mandatory_end_date, discharge_date)

    return MappedSoldierFields(
        full_name=hr_user.full_name,
        personal_number=hr_user.personal_number,
        email=hr_user.mail,
        phone=hr_user.phone,
        profile_picture_url=hr_user.image_url,
        gender=mapped_gender,
        rank=mapped_rank,
        rank_track=mapped_track,
        is_officer=is_officer,
        is_career=is_career,
        enlistment_date=enlistment_date,
        mandatory_end_date=mandatory_end_date,
        discharge_date=discharge_date,
    )
