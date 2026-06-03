from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
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
    for key, value in body.settings.items():
        if key in _HIDDEN_KEYS:
            continue
        set_setting(session, key=key, value=value, actor_id=user.id)
    session.commit()
    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})
