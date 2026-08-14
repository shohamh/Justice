from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed, require_roles
from app.db.models import Soldier
from app.db.session import get_session
from app.services.rank_advancement import (
    Track,
    get_rank_ladder,
    get_track,
    set_interval_and_recompute,
)

router = APIRouter(prefix="/soldiers", tags=["rank-advancement"])


class RankIntervalIn(BaseModel):
    # `track` is constrained to the two real ladders and `months_to_next` to a
    # sane positive number of months: without this an admin typo could persist
    # junk (track, rank) rows that get_rank_ladder() never surfaces (so they can
    # never be seen or cleaned up from the UI), or a 0/negative interval — 0
    # makes the projection chain-walk spin to its safety bound on the solver's
    # hot path, and a negative one walks next_rank_date backwards, which would
    # make the daily worker promote the soldier again on every single run.
    track: Track
    rank: str
    months_to_next: Annotated[int, Field(ge=1)] | None
    advance_on_career_entry: bool = False

    @model_validator(mode="after")
    def _validate_rank_in_track(self) -> "RankIntervalIn":
        if get_track(self.rank) != self.track:
            raise ValueError(f"rank {self.rank!r} is not part of the {self.track!r} ladder")
        return self


@router.get("/rank-ladder")
def read_rank_ladder(
    session: Session = Depends(get_session),
    _user: Soldier = Depends(require_password_changed),
) -> dict:
    return get_rank_ladder(session)


@router.put("/rank-advancement-intervals")
def update_rank_advancement_intervals(
    intervals: list[RankIntervalIn],
    session: Session = Depends(get_session),
    admin: Soldier = Depends(require_roles("admin")),
) -> dict:
    for item in intervals:
        set_interval_and_recompute(
            session,
            track=item.track,
            rank=item.rank,
            months_to_next=item.months_to_next,
            advance_on_career_entry=item.advance_on_career_entry,
            actor_id=admin.id,
        )
    session.commit()
    return get_rank_ladder(session)
