from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier, SystemSetting
from app.db.session import get_session

router = APIRouter(prefix="/settings/public", tags=["settings"])

_PUBLIC_KEYS = {
    "gimalim.enabled",
    "gimalim.default_rest_days",
    "gimalim.reserve_fate",
    "shifts.auto_split_node_quotas",
}


class PublicSettingsOut(BaseModel):
    settings: dict


@router.get("", response_model=PublicSettingsOut)
def get_public_settings(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PublicSettingsOut:
    rows = session.execute(select(SystemSetting)).scalars().all()
    return PublicSettingsOut(settings={r.key: r.value for r in rows if r.key in _PUBLIC_KEYS})
