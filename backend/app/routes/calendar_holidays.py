from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import holidays as hol

from app.auth.deps import require_password_changed
from app.db.models import Soldier

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/holidays")
def list_holidays(
    year: int = Query(ge=1900, le=2100),
    _user: Soldier = Depends(require_password_changed),
) -> list[dict]:
    il = hol.country_holidays("IL", years=year)
    return [{"date": str(d), "name": name} for d, name in sorted(il.items())]
