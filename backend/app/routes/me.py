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
    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
        hierarchy_node_id=user.hierarchy_node_id,
        telegram_linked=link is not None,
        telegram_required=telegram_required,
    )
