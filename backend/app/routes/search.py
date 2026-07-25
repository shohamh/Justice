from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services.search import search_duties, search_soldiers, search_units

router = APIRouter(prefix="/search", tags=["search"])


class SoldierResult(BaseModel):
    id: str
    full_name: str
    personal_number: str
    subtitle: str | None


class DutyResult(BaseModel):
    id: str
    duty_type_name: str
    start_date: str
    end_date: str
    location_name: str


class UnitResult(BaseModel):
    id: str
    name: str
    level: str


class SearchResponse(BaseModel):
    soldiers: list[SoldierResult]
    duties: list[DutyResult]
    units: list[UnitResult]


@router.get("", response_model=SearchResponse)
def search(
    q: str = "",
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SearchResponse:
    return SearchResponse(
        soldiers=search_soldiers(session, user=user, query=q),
        duties=search_duties(session, user=user, query=q),
        units=search_units(session, user=user, query=q),
    )
