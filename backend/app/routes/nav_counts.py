from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services.nav_counts import get_nav_counts

router = APIRouter(tags=["navigation"])


class NavCountsOut(BaseModel):
    approvals: int
    hakpaza: int
    incoming_swaps: int


@router.get("/nav/counts", response_model=NavCountsOut)
def nav_counts(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NavCountsOut:
    return NavCountsOut(**get_nav_counts(session, user))
