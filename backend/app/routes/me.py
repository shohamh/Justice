from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import is_commander, is_duty_manager
from app.auth.deps import get_current_user, require_password_changed
from app.db.models import HierarchyNode, Soldier, SoldierEnrollmentRequest, TelegramLink
from app.db.session import get_session
from app.services import email_verification as ev_svc
from app.services.settings_loader import get_setting

router = APIRouter(prefix="/me", tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    is_commander: bool
    is_duty_manager: bool
    must_change_password: bool
    hierarchy_node_id: uuid.UUID | None
    telegram_linked: bool
    telegram_required: bool
    phone: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: str | None = None
    enlistment_date: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    email: str | None = None
    email_verified: bool = False
    direct_commander_id: uuid.UUID | None = None
    direct_commander_name: str | None = None
    profile_picture_url: str | None = None
    is_career: bool = False
    enrollment_pending: bool = False
    theme_preference: str = "system"


class SetEmailRequest(BaseModel):
    email: str | None = Field(default=None, max_length=200)


def _direct_commander(session: Session, s: Soldier) -> Soldier | None:
    if s.hierarchy_node_id is None:
        return None
    node = session.get(HierarchyNode, s.hierarchy_node_id)
    if node is None:
        return None
    if node.commander_id and node.commander_id != s.id:
        return session.get(Soldier, node.commander_id)
    if node.parent_id is None:
        return None
    parent = session.get(HierarchyNode, node.parent_id)
    if parent is None or parent.commander_id is None or parent.commander_id == s.id:
        return None
    return session.get(Soldier, parent.commander_id)


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
        telegram_required = False  # default: telegram linking is optional

    def _date(d) -> str | None:
        return str(d) if d is not None else None

    commander = _direct_commander(session, user)

    enrollment_pending = session.execute(
        select(SoldierEnrollmentRequest.id).where(
            SoldierEnrollmentRequest.soldier_id == user.id,
            SoldierEnrollmentRequest.status.in_(("pending", "commander_approved")),
        ).limit(1)
    ).first() is not None

    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
        must_change_password=user.must_change_password,
        hierarchy_node_id=user.hierarchy_node_id,
        telegram_linked=link is not None,
        telegram_required=telegram_required,
        phone=user.phone,
        gender=user.gender,
        is_officer=user.is_officer,
        rank=user.rank,
        bahad1_graduate=user.bahad1_graduate or False,
        has_military_driving_license=user.has_military_driving_license,
        military_driving_license_expiry=_date(user.military_driving_license_expiry),
        enlistment_date=_date(user.enlistment_date),
        mandatory_end_date=_date(user.mandatory_end_date),
        discharge_date=_date(user.discharge_date),
        last_mitvahim_date=_date(user.last_mitvahim_date),
        last_alal_date=_date(user.last_alal_date),
        email=user.email,
        email_verified=user.email_verified,
        direct_commander_id=commander.id if commander else None,
        direct_commander_name=commander.full_name if commander else None,
        profile_picture_url=user.profile_picture_url,
        is_career=user.is_career,
        enrollment_pending=enrollment_pending,
        theme_preference=user.theme_preference,
    )


@router.patch("/email", status_code=200)
def set_email(
    body: Annotated[SetEmailRequest, Body()],
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    new_email = body.email or None
    changed = user.email != new_email
    user.email = new_email
    if changed:
        user.email_verified = False
    if new_email and changed:
        ev_svc.request_verification(session, soldier=user)
    session.commit()
    return {"email_verified": user.email_verified}
