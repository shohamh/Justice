from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import SystemSetting
from app.db.session import get_session
from app.services.settings_loader import set_setting

router = APIRouter(prefix="/admin/system-settings", tags=["system_settings"])

# Keys that the UI should never expose (internal/read-only)
_HIDDEN_KEYS = {"system.holding_node_id"}

_DENSITY_DEFAULTS = {
    "algorithm.max_duties_per_window": 8,
    "algorithm.max_total_duties_per_window": 8,
    "algorithm.relax_t_ceiling": 10,
    "algorithm.relax_r_ceiling": 12,
}


class SettingsOut(BaseModel):
    settings: dict[str, Any]


class UpdateSettingsBody(BaseModel):
    settings: dict[str, Any]


@router.get("", response_model=SettingsOut)
def get_settings_endpoint(
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})


@router.put("", response_model=SettingsOut)
def update_settings(
    body: UpdateSettingsBody,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    existing = {r.key: r.value for r in session.execute(select(SystemSetting)).scalars().all()}
    merged = {**existing, **body.settings}

    def _density(key: str) -> int:
        return int(merged.get(key, _DENSITY_DEFAULTS[key]))

    t = _density("algorithm.max_duties_per_window")
    r = _density("algorithm.max_total_duties_per_window")
    t_ceil = _density("algorithm.relax_t_ceiling")
    r_ceil = _density("algorithm.relax_r_ceiling")

    if t > r:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="t_exceeds_r")
    if t_ceil > r_ceil or t > t_ceil or r > r_ceil:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="relax_ceiling_invalid")

    for key, value in body.settings.items():
        if key in _HIDDEN_KEYS:
            continue
        set_setting(session, key=key, value=value, actor_id=user.id)
    session.commit()
    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})
