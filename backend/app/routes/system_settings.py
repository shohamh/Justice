from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import SystemSetting
from app.db.session import get_session
from app.services.settings_loader import (
    _HIDDEN_KEYS,
    SettingsValidationError,
    apply_settings,
    weapon_enforcement_changed,
)

router = APIRouter(prefix="/admin/system-settings", tags=["system_settings"])


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
    _weapon_setting_changed = weapon_enforcement_changed(existing, body.settings)
    try:
        apply_settings(session, existing, body.settings, actor_id=user.id)
    except SettingsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)
    session.commit()

    if _weapon_setting_changed:
        from app.db.models import DutyAssignment, DutyType
        from app.services.duty_eligibility_watch import recheck_assignments

        weapon_type_ids = session.execute(
            select(DutyType.id).where(DutyType.required_range_type.is_not(None))
        ).scalars().all()
        if weapon_type_ids:
            affected_ids = session.execute(
                select(DutyAssignment.id).where(
                    DutyAssignment.duty_type_id.in_(weapon_type_ids),
                    DutyAssignment.status == "published",
                )
            ).scalars().all()
            if affected_ids:
                recheck_assignments(session, affected_ids)

    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})


@router.get("/export", response_model=SettingsOut)
def export_settings(
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})


@router.post("/import", response_model=SettingsOut)
def import_settings(
    body: UpdateSettingsBody,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    return update_settings(body, session, user)
