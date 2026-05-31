from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import ShiftTemplate, Soldier
from app.db.session import get_session
from app.services import shift_templates as svc

router = APIRouter(prefix="/shift-templates", tags=["shift-templates"])


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    weekdays: list[int]
    start_time: str
    end_time: str
    required_count: int
    active: bool
    auto_roll: bool
    notes: str | None


class CreateTemplateRequest(BaseModel):
    name: str = Field(max_length=200)
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    weekdays: list[int]
    start_time: str = "00:00"
    end_time: str = "23:59"
    required_count: int = Field(default=1, ge=1)
    auto_roll: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    weekdays: list[int] | None = None
    start_time: str | None = None
    end_time: str | None = None
    required_count: int | None = Field(default=None, ge=1)
    auto_roll: bool | None = None
    active: bool | None = None
    notes: str | None = None


class GenerateRequest(BaseModel):
    range_start: date
    range_end: date


class PreviewRow(BaseModel):
    date: date
    exists: bool


class GenerateResult(BaseModel):
    created_count: int


def _out(t: ShiftTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id, name=t.name, duty_type_id=t.duty_type_id, duty_location_id=t.duty_location_id,
        weekdays=t.weekdays, start_time=t.start_time, end_time=t.end_time,
        required_count=t.required_count, active=t.active, auto_roll=t.auto_roll, notes=t.notes,
    )


def _load(session: Session, template_id: uuid.UUID) -> ShiftTemplate:
    t = session.get(ShiftTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return t


@router.get("", response_model=list[TemplateOut])
def list_templates(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TemplateOut]:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    return [_out(t) for t in svc.list_templates(session, include_inactive=include_inactive)]


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: CreateTemplateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TemplateOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    try:
        t = svc.create_template(
            session, name=body.name, duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id, weekdays=body.weekdays,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            notes=body.notes, actor_id=user.id,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: uuid.UUID,
    body: UpdateTemplateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TemplateOut:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    extra: dict = {}
    if "notes" in body.model_fields_set:
        extra["notes"] = body.notes
    try:
        svc.update_template(
            session, tpl=t, name=body.name, weekdays=body.weekdays,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            active=body.active, actor_id=user.id, **extra,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    svc.delete_template(session, tpl=t, actor_id=user.id)
    session.commit()


@router.post("/{template_id}/preview", response_model=list[PreviewRow])
def preview(
    template_id: uuid.UUID,
    body: GenerateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[PreviewRow]:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    rows = svc.preview_generation(session, tpl=t, range_start=body.range_start, range_end=body.range_end)
    return [PreviewRow(date=r["date"], exists=r["exists"]) for r in rows]


@router.post("/{template_id}/generate", response_model=GenerateResult)
def generate(
    template_id: uuid.UUID,
    body: GenerateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> GenerateResult:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    created = svc.generate_shifts(
        session, tpl=t, range_start=body.range_start, range_end=body.range_end, actor_id=user.id
    )
    session.commit()
    return GenerateResult(created_count=len(created))
