from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Soldier, TelegramLink
from app.db.session import get_session
from app.services.settings_loader import get_setting

router = APIRouter(prefix="/me", tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    must_change_password: bool
    hierarchy_node_id: uuid.UUID | None
    telegram_linked: bool
    telegram_required: bool
    phone: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None


@router.get("", response_model=MeResponse)
def me(
    user: Soldier = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MeResponse:
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == user.id,
            TelegramLink.is_verified == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    try:
        telegram_required = bool(get_setting(session, "registration.telegram_required"))
    except Exception:
        telegram_required = True
    def _date(d) -> str | None:
        return str(d) if d is not None else None

    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
        hierarchy_node_id=user.hierarchy_node_id,
        telegram_linked=link is not None,
        telegram_required=telegram_required,
        phone=user.phone,
        gender=user.gender,
        is_officer=user.is_officer,
        rank=user.rank,
        bahad1_graduate=user.bahad1_graduate or False,
        enlistment_date=_date(user.enlistment_date),
        mandatory_end_date=_date(user.mandatory_end_date),
        discharge_date=_date(user.discharge_date),
        last_mitvahim_date=_date(user.last_mitvahim_date),
        last_alal_date=_date(user.last_alal_date),
    )
