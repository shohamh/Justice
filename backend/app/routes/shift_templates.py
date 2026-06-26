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
    recurrence_type: str
    weekdays: list[int]
    duration_days: int
    start_time: str
    end_time: str
    required_count: int
    active: bool
    auto_roll: bool
    auto_roll_until: date | None
    notes: str | None
    eligible_node_ids: list[uuid.UUID] | None = None


class CreateTemplateRequest(BaseModel):
    name: str = Field(max_length=200)
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    recurrence_type: str = "weekly"
    weekdays: list[int] = Field(default_factory=list)
    duration_days: int = Field(default=1, ge=1, le=14)
    start_time: str = "00:00"
    end_time: str = "23:59"
    required_count: int = Field(default=1, ge=1)
    auto_roll: bool = False
    auto_roll_until: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    eligible_node_ids: list[uuid.UUID] | None = None


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    recurrence_type: str | None = None
    weekdays: list[int] | None = None
    duration_days: int | None = Field(default=None, ge=1, le=14)
    start_time: str | None = None
    end_time: str | None = None
    required_count: int | None = Field(default=None, ge=1)
    auto_roll: bool | None = None
    auto_roll_until: date | None = None
    active: bool | None = None
    notes: str | None = None
    eligible_node_ids: list[uuid.UUID] | None = None


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
        recurrence_type=t.recurrence_type, weekdays=t.weekdays, duration_days=t.duration_days,
        start_time=t.start_time, end_time=t.end_time, required_count=t.required_count,
        active=t.active, auto_roll=t.auto_roll, auto_roll_until=t.auto_roll_until, notes=t.notes,
        eligible_node_ids=t.eligible_node_ids,
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
            duty_location_id=body.duty_location_id, recurrence_type=body.recurrence_type,
            weekdays=body.weekdays, duration_days=body.duration_days,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            auto_roll_until=body.auto_roll_until,
            notes=body.notes, eligible_node_ids=body.eligible_node_ids, actor_id=user.id,
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
    if "auto_roll_until" in body.model_fields_set:
        extra["auto_roll_until"] = body.auto_roll_until
    if "eligible_node_ids" in body.model_fields_set:
        extra["eligible_node_ids"] = body.eligible_node_ids
    try:
        svc.update_template(
            session, tpl=t, name=body.name, recurrence_type=body.recurrence_type,
            weekdays=body.weekdays, duration_days=body.duration_days,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            active=body.active, actor_id=user.id, **extra,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
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
