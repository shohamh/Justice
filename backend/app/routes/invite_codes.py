from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import RegistrationInviteCode
from app.db.session import get_session
from app.services import invite_codes as svc

router = APIRouter(prefix="/admin/invite-codes", tags=["invite_codes"])


class CreateCodeRequest(BaseModel):
    uses_left: int = Field(ge=1, le=100)


class InviteCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    uses_left: int
    created_by: uuid.UUID | None


@router.get("", response_model=list[InviteCodeOut])
def list_codes(
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> list[InviteCodeOut]:
    codes = session.execute(select(RegistrationInviteCode)).scalars().all()
    return [InviteCodeOut(id=c.id, code=c.code, uses_left=c.uses_left, created_by=c.created_by) for c in codes]


@router.post("", response_model=InviteCodeOut, status_code=status.HTTP_201_CREATED)
def create_code(
    body: CreateCodeRequest,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> InviteCodeOut:
    code = svc.create_invite_code(session, uses_left=body.uses_left, actor_id=user.id)
    session.commit()
    return InviteCodeOut(id=code.id, code=code.code, uses_left=code.uses_left, created_by=code.created_by)


@router.delete("/{code_id}")
def revoke_code(
    code_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> dict:
    code = session.get(RegistrationInviteCode, code_id)
    if code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    session.delete(code)
    session.commit()
    return {"status": "ok"}
