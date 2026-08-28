from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.services.holidays import calendar_holidays_for_year

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/holidays")
def list_holidays(
    year: int = Query(ge=1900, le=2100),
    _user: Soldier = Depends(require_password_changed),
) -> list[dict]:
    il = calendar_holidays_for_year(year)
    return [{"date": str(d), "name": name} for d, name in sorted(il.items())]
