from __future__ import annotations

from fastapi import APIRouter
import holidays as hol

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/holidays")
def list_holidays(year: int) -> list[dict]:
    il = hol.country_holidays("IL", years=year)
    return [{"date": str(d), "name": name} for d, name in sorted(il.items())]
