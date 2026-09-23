from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services.hr_activation import ActivationCodeError, generate_activation_code

router = APIRouter(prefix="/soldiers", tags=["hr_activation"])


class ActivationCodeOut(BaseModel):
    code: str
    expires_at: datetime


@router.post("/{soldier_id}/activation-code", response_model=ActivationCodeOut)
def create_activation_code(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
) -> ActivationCodeOut:
    try:
        code = generate_activation_code(session, target_soldier_id=soldier_id, actor=actor)
    except ActivationCodeError as exc:
        session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail in ("soldier_not_found", "not_hr_linked") else (
            status.HTTP_409_CONFLICT if detail == "already_activated" else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    session.commit()
    return ActivationCodeOut(code=code.code, expires_at=code.expires_at)
