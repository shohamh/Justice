from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import RankAdvancementInterval, Soldier
from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS

Track = Literal["enlisted", "officer"]

_LADDERS: dict[Track, list[str]] = {"enlisted": ENLISTED_RANKS, "officer": OFFICER_RANKS}


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
    session: Session, *, track: str, rank: str, months_to_next: int | None, actor_id: uuid.UUID | None
) -> RankAdvancementInterval:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    before = None if row is None else row.months_to_next
    if row is None:
        row = RankAdvancementInterval(track=track, rank=rank, months_to_next=months_to_next)
        session.add(row)
    else:
        row.months_to_next = months_to_next
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="rank_advancement_interval.upsert",
        entity_type="rank_advancement_interval",
        entity_id=row.id,
        before={"months_to_next": before},
        after={"months_to_next": months_to_next},
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
    session: Session, *, track: str, rank: str, months_to_next: int | None, actor_id: uuid.UUID | None
) -> int:
    upsert_interval(session, track=track, rank=rank, months_to_next=months_to_next, actor_id=actor_id)
    return recompute_affected_soldiers(session, track=track, rank=rank)


def get_rank_ladder(session: Session) -> dict[str, list[dict]]:
    rows = session.execute(select(RankAdvancementInterval)).scalars().all()
    months_by = {(r.track, r.rank): r.months_to_next for r in rows}
    return {
        track: [{"rank": rank, "months_to_next": months_by.get((track, rank))} for rank in ladder]
        for track, ladder in _LADDERS.items()
    }
