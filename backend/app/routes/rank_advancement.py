from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed, require_roles
from app.db.models import Soldier
from app.db.session import get_session
from app.services.rank_advancement import get_rank_ladder, set_interval_and_recompute

router = APIRouter(prefix="/soldiers", tags=["rank-advancement"])


class RankIntervalIn(BaseModel):
    track: str
    rank: str
    months_to_next: int | None


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
            actor_id=admin.id,
        )
    session.commit()
    return get_rank_ladder(session)
