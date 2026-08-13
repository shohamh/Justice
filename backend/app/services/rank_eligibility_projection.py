from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import Soldier
from app.services.eligibility import derive_is_career
from app.services.rank_advancement import compute_next_rank_date, get_next_rank


@dataclass(frozen=True)
class ProjectedSoldierState:
    rank: str | None
    is_career: bool
    departed: bool


_MAX_CHAIN_STEPS = 24  # safety bound; a soldier cannot realistically advance
                        # more than a couple of ranks within any real duty
                        # planning horizon, this just prevents a runaway loop
                        # on misconfigured (e.g. zero-month) intervals.


def project_soldier_state(session: Session, *, soldier: Soldier, as_of: date) -> ProjectedSoldierState:
    rank = soldier.rank
    next_date = soldier.next_rank_date
    for _ in range(_MAX_CHAIN_STEPS):
        if rank is None or next_date is None or next_date > as_of:
            break
        next_rank = get_next_rank(rank)
        if next_rank is None:
            break
        rank = next_rank
        next_date = compute_next_rank_date(session, rank=rank, since=next_date)

    is_career = derive_is_career(rank, soldier.mandatory_end_date, soldier.discharge_date, today=as_of)

    departed = False
    if soldier.discharge_date is not None and soldier.discharge_date <= as_of:
        departed = True
    if soldier.left_at is not None and soldier.left_at <= as_of:
        departed = True

    return ProjectedSoldierState(rank=rank, is_career=is_career, departed=departed)
