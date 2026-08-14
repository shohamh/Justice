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
# ADVANCEMENT chain, which is a different (and narrower) concept: קמא sits
# outside every automated ladder (promoting off it is a manual action), and
# קאב/קאם belong exclusively to the academic officer track now, not the
# regular one -- the same rank name chains to a different "next rank"
# depending on which track the officer is actually on.
ENLISTED_LADDER = ENLISTED_RANKS
OFFICER_LADDER = ["סגמ", "סגן", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]
OFFICER_ACADEMIC_LADDER = ["קאב", "קאם"]

Track = Literal["enlisted", "officer", "officer_academic"]

_LADDERS: dict[Track, list[str]] = {
    "enlisted": ENLISTED_LADDER,
    "officer": OFFICER_LADDER,
    "officer_academic": OFFICER_ACADEMIC_LADDER,
}


def get_track(rank: str) -> Track | None:
    for track, ladder in _LADDERS.items():
        if rank in ladder:
            return track
    return None


def get_next_rank(rank: str) -> str | None:
    track = get_track(rank)
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
    return row.months_to_next if row is not None else None


def compute_next_rank_date(session: Session, *, rank: str, since: date) -> date | None:
    track = get_track(rank)
    if track is None:
        return None
    months = get_interval_months(session, track=track, rank=rank)
    if months is None:
        return None
    return since + relativedelta(months=months)


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
    soldiers = session.execute(
        select(Soldier).where(Soldier.rank == rank, Soldier.next_rank_date_overridden.is_(False))
    ).scalars().all()
    updated = 0
    for s in soldiers:
        since = s.current_rank_since or s.enlistment_date
        if since is None:
            continue
        s.next_rank_date = compute_next_rank_date(session, rank=rank, since=since)
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
    return row.advance_on_career_entry if row is not None else False


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
                "months_to_next": row.months_to_next if (row := by_key.get((track, rank))) is not None else None,
                "advance_on_career_entry": bool(row and row.advance_on_career_entry),
            }
            for rank in ladder
        ]
        for track, ladder in _LADDERS.items()
    }
