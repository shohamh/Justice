from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import RankAdvancementInterval, Soldier
from app.services.eligibility import ENLISTED_RANKS

# eligibility.py's ENLISTED_RANKS/OFFICER_RANKS are rank-VALIDITY lists (used
# for gender/service-type checks, בה"ד 1 inference, RANK_TRACK_COMPATIBILITY)
# and are deliberately left untouched -- a soldier can still hold, and be
# validated as holding, any of those ranks. These ladders below are only the
# ADVANCEMENT chain, which is a different (and narrower) concept. Academic
# officers start at קמא, advance through קאב, then enter the regular officer
# ranks at סגן. קאם is retained as the final academic-only rank for ordering.
ENLISTED_LADDER = ENLISTED_RANKS
OFFICER_LADDER = ["סגמ", "סגן", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]
OFFICER_ACADEMIC_LADDER = [
    "קמא", "קאב", "סגן", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף", "קאם",
]

Track = Literal["enlisted", "officer", "officer_academic"]

_LADDERS: dict[Track, list[str]] = {
    "enlisted": ENLISTED_LADDER,
    "officer": OFFICER_LADDER,
    "officer_academic": OFFICER_ACADEMIC_LADDER,
}

# Runtime defaults mirror the values shown in the admin system-settings page.
# A database row still wins, including an explicit NULL interval, so an admin
# can disable automatic advancement for a rank after the seed has run.
DEFAULT_RANK_ADVANCEMENT_INTERVALS: tuple[tuple[Track, str, int | None, bool], ...] = (
    ("enlisted", "טוראי", 10, False),
    ("enlisted", "רבט", 11, False),
    ("enlisted", "סמל", 11, True),
    ("enlisted", "סמר", 24, False),
    ("enlisted", "רסל", None, False),
    ("enlisted", "רסר", None, False),
    ("enlisted", "רסמ", None, False),
    ("enlisted", "רסב", None, False),
    ("enlisted", "רנג", None, False),
    ("officer", "סגמ", 12, True),
    ("officer", "סגן", 36, False),
    ("officer", "סרן", 48, False),
    ("officer", "רסן", None, False),
    ("officer", "סאל", None, False),
    ("officer", "אלמ", None, False),
    ("officer", "תאל", None, False),
    ("officer", "אלוף", None, False),
    ("officer", "רב אלוף", None, False),
    ("officer_academic", "קמא", 32, True),
    ("officer_academic", "קאב", None, False),
    ("officer_academic", "סגן", 12, True),
    ("officer_academic", "סרן", 36, False),
    ("officer_academic", "רסן", None, False),
    ("officer_academic", "סאל", None, False),
    ("officer_academic", "אלמ", None, False),
    ("officer_academic", "תאל", None, False),
    ("officer_academic", "אלוף", None, False),
    ("officer_academic", "רב אלוף", None, False),
    ("officer_academic", "קאם", None, False),
)
_DEFAULT_INTERVALS_BY_KEY = {
    (track, rank): (months_to_next, advance_on_career_entry)
    for track, rank, months_to_next, advance_on_career_entry in DEFAULT_RANK_ADVANCEMENT_INTERVALS
}


def get_track(rank: str, *, track: Track | None = None) -> Track | None:
    """Return the advancement track for a rank.

    Shared officer ranks default to the regular track for legacy callers.
    Callers holding a soldier's persisted track must pass it explicitly so
    academic-specific intervals continue to apply after קאב -> סגן.
    """
    if track is not None:
        ladder = _LADDERS.get(track)
        return track if ladder is not None and rank in ladder else None
    matches = [candidate for candidate, ladder in _LADDERS.items() if rank in ladder]
    if not matches:
        return None
    return "officer" if "officer" in matches else matches[0]


def resolve_track(rank: str | None, stored_track: str | None) -> Track | None:
    """Resolve a soldier's track, retaining it across shared officer ranks."""
    if rank is None:
        return None
    if stored_track in _LADDERS and rank in _LADDERS[stored_track]:
        return stored_track
    return get_track(rank)


def get_next_rank(rank: str, *, track: Track | None = None) -> str | None:
    track = get_track(rank, track=track)
    if track is None:
        return None
    ladder = _LADDERS[track]
    idx = ladder.index(rank)
    if idx + 1 >= len(ladder):
        return None
    return ladder[idx + 1]


def get_interval_months(session: Session, *, track: str, rank: str) -> int | None:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.months_to_next
    return _DEFAULT_INTERVALS_BY_KEY.get((track, rank), (None, False))[0]


def compute_next_rank_date(
    session: Session, *, rank: str, since: date, track: Track | None = None
) -> date | None:
    track = get_track(rank, track=track)
    if track is None:
        return None
    months = get_interval_months(session, track=track, rank=rank)
    if months is None:
        return None
    return since + relativedelta(months=months)


def compute_initial_next_rank_date(
    session: Session,
    *,
    rank: str,
    enlistment_date: date | None,
    fallback_since: date,
    track: Track | None = None,
) -> date | None:
    """Schedule an initially assigned rank from cumulative enlistment service."""
    resolved_track = get_track(rank, track=track)
    if resolved_track is None:
        return None
    if enlistment_date is None:
        return compute_next_rank_date(
            session, rank=rank, since=fallback_since, track=resolved_track
        )

    ladder = _LADDERS[resolved_track]
    total_months = 0
    for ladder_rank in ladder[:ladder.index(rank) + 1]:
        months = get_interval_months(session, track=resolved_track, rank=ladder_rank)
        if months is None:
            return None
        total_months += months
    return enlistment_date + relativedelta(months=total_months)


def compute_next_rank_date_for_soldier(session: Session, *, soldier: Soldier) -> date | None:
    """Schedule a soldier from enlistment until a system promotion establishes a new anchor."""
    if soldier.rank is None:
        return None
    track = resolve_track(soldier.rank, soldier.rank_track)
    if track is None:
        return None
    if soldier.current_rank_since is None or soldier.current_rank_since == soldier.enlistment_date:
        return compute_initial_next_rank_date(
            session,
            rank=soldier.rank,
            enlistment_date=soldier.enlistment_date,
            fallback_since=soldier.current_rank_since or date.today(),
            track=track,
        )
    return compute_next_rank_date(
        session, rank=soldier.rank, since=soldier.current_rank_since, track=track
    )


def upsert_interval(
    session: Session, *, track: str, rank: str, months_to_next: int | None,
    advance_on_career_entry: bool, actor_id: uuid.UUID | None,
) -> RankAdvancementInterval:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    before = None if row is None else {
        "months_to_next": row.months_to_next, "advance_on_career_entry": row.advance_on_career_entry,
    }
    if row is None:
        row = RankAdvancementInterval(
            track=track, rank=rank, months_to_next=months_to_next,
            advance_on_career_entry=advance_on_career_entry,
        )
        session.add(row)
    else:
        row.months_to_next = months_to_next
        row.advance_on_career_entry = advance_on_career_entry
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="rank_advancement_interval.upsert",
        entity_type="rank_advancement_interval",
        entity_id=row.id,
        before=before,
        after={"months_to_next": months_to_next, "advance_on_career_entry": advance_on_career_entry},
    )
    return row


def recompute_affected_soldiers(session: Session, *, track: str, rank: str) -> int:
    ladder = _LADDERS.get(track)
    if ladder is None or rank not in ladder:
        return 0
    affected_initial_ranks = ladder[ladder.index(rank):]
    soldiers = session.execute(
        select(Soldier).where(
            Soldier.rank.in_(affected_initial_ranks),
            Soldier.next_rank_date_overridden.is_(False),
        )
    ).scalars().all()
    updated = 0
    for s in soldiers:
        soldier_track = resolve_track(s.rank, s.rank_track)
        if soldier_track != track:
            continue
        uses_cumulative_enlistment = (
            s.enlistment_date is not None
            and (s.current_rank_since is None or s.current_rank_since == s.enlistment_date)
        )
        if not uses_cumulative_enlistment and s.rank != rank:
            continue
        s.next_rank_date = compute_next_rank_date_for_soldier(session, soldier=s)
        updated += 1
    return updated


def set_interval_and_recompute(
    session: Session, *, track: str, rank: str, months_to_next: int | None,
    advance_on_career_entry: bool, actor_id: uuid.UUID | None,
) -> int:
    upsert_interval(
        session, track=track, rank=rank, months_to_next=months_to_next,
        advance_on_career_entry=advance_on_career_entry, actor_id=actor_id,
    )
    return recompute_affected_soldiers(session, track=track, rank=rank)


def advances_on_career_entry(session: Session, *, track: str, rank: str) -> bool:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.advance_on_career_entry
    return _DEFAULT_INTERVALS_BY_KEY.get((track, rank), (None, False))[1]


def _career_entry_date(mandatory_end_date: date | None, discharge_date: date | None) -> date | None:
    """The first calendar day this soldier is career (קבע), or None if they
    never reach it -- mirrors derive_is_career's exact True/False boundary
    (eligibility.py) as a single date instead of a per-call boolean, so it
    can be compared against other candidate advancement dates."""
    if mandatory_end_date is None:
        return None
    if discharge_date is not None and discharge_date <= mandatory_end_date:
        return None
    return mandatory_end_date + timedelta(days=1)


def _career_entry_applies_to_current_rank(
    *,
    entry_date: date | None,
    current_rank_since: date | None,
    enlistment_date: date | None,
) -> bool:
    """Whether the current rank was held strictly before career entry.

    Legacy rows can lack current_rank_since; rank advancement already treats
    enlistment_date as their rank-attainment fallback when recomputing
    schedules, so the career-entry trigger follows the same model semantics.
    If neither date is known, the historical event cannot safely be applied.

    Equality is deliberately excluded: a career-entry promotion stamps its
    successor's current_rank_since to entry_date, so equality means that event
    has already been consumed and cannot promote the successor on a later run.
    """
    rank_since = current_rank_since or enlistment_date
    return entry_date is not None and rank_since is not None and rank_since < entry_date


def get_rank_ladder(session: Session) -> dict[str, list[dict]]:
    rows = session.execute(select(RankAdvancementInterval)).scalars().all()
    by_key = {(r.track, r.rank): r for r in rows}
    return {
        track: [
            {
                "rank": rank,
                "months_to_next": (
                    row.months_to_next
                    if (row := by_key.get((track, rank))) is not None
                    else _DEFAULT_INTERVALS_BY_KEY.get((track, rank), (None, False))[0]
                ),
                "advance_on_career_entry": (
                    row.advance_on_career_entry
                    if row is not None
                    else _DEFAULT_INTERVALS_BY_KEY.get((track, rank), (None, False))[1]
                ),
            }
            for rank in ladder
        ]
        for track, ladder in _LADDERS.items()
    }
