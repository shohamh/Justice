from __future__ import annotations

import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import RoleDeputy, Soldier
from app.db.session import get_session
from app.services import deputies as svc

router = APIRouter(prefix="/deputies", tags=["deputies"])


class CreateDeputyRequest(BaseModel):
    principal_id: uuid.UUID
    deputy_id: uuid.UUID
    role: str
    start_date: date_type
    end_date: date_type


class DeputyOut(BaseModel):
    id: uuid.UUID
    principal_id: uuid.UUID
    principal_name: str
    deputy_id: uuid.UUID
    deputy_name: str
    role: str
    start_date: date_type
    end_date: date_type


def _out(session: Session, entry: RoleDeputy) -> DeputyOut:
    principal = session.get(Soldier, entry.principal_id)
    deputy = session.get(Soldier, entry.deputy_id)
    return DeputyOut(
        id=entry.id,
        principal_id=entry.principal_id,
        principal_name=principal.full_name if principal else "",
        deputy_id=entry.deputy_id,
        deputy_name=deputy.full_name if deputy else "",
        role=entry.role,
        start_date=entry.start_date,
        end_date=entry.end_date,
    )


def _assert_self_or_admin(user: Soldier, principal_id: uuid.UUID) -> None:
    if user.role != "admin" and user.id != principal_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.post("", response_model=DeputyOut, status_code=status.HTTP_201_CREATED)
def create_deputy(
    body: CreateDeputyRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> DeputyOut:
    _assert_self_or_admin(user, body.principal_id)
    try:
        entry = svc.create_deputy(
            session,
            principal_id=body.principal_id,
            deputy_id=body.deputy_id,
            role=body.role,
            start_date=body.start_date,
            end_date=body.end_date,
            actor_id=user.id,
        )
        session.commit()
        return _out(session, entry)
    except svc.DeputyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[DeputyOut])
def list_deputies(
    principal_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[DeputyOut]:
    _assert_self_or_admin(user, principal_id)
    entries = svc.list_deputies(session, principal_id=principal_id)
    return [_out(session, e) for e in entries]


@router.delete("/{deputy_grant_id}", status_code=status.HTTP_200_OK)
def revoke_deputy(
    deputy_grant_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    entry = session.get(RoleDeputy, deputy_grant_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    _assert_self_or_admin(user, entry.principal_id)
    try:
        svc.revoke_deputy(session, deputy_grant_id=deputy_grant_id, actor_id=user.id)
        session.commit()
        return {"status": "ok"}
    except svc.DeputyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
