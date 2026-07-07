from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.eligibility import DutyTypeRequirements

from app.auth.deps import require_duty_manager_or_admin, require_password_changed
from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, ExemptionDutyTypeMap, ExemptionType, ShiftTemplate, Soldier
from app.db.session import get_session
from app.services import duty_config as svc

router = APIRouter(prefix="/duty-config", tags=["duty-config"])


def require_config_manager(
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> Soldier:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user


# ---- duty types ----
class DutyTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    score_per_day: Decimal
    description: str | None
    active: bool
    requirements: dict[str, Any] = {}
    reserve_ratio: Decimal = Decimal("0.000")
    reserve_minimum: int = 0
    contact_name: str | None = None
    contact_phone: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    instructions: str | None = None
    is_external: bool = False
    eligible_node_ids: list[uuid.UUID] | None = None


class CreateDutyTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    score_per_day: Decimal = Field(ge=0)
    description: str | None = Field(default=None, max_length=1000)
    reserve_ratio: Decimal = Field(default=Decimal("0.000"), ge=0, le=1)
    reserve_minimum: int = Field(default=0, ge=0)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    start_time: time | None = None
    end_time: time | None = None
    instructions: str | None = Field(default=None)
    is_external: bool  # required — no default
    eligible_node_ids: list[uuid.UUID] | None = None

    @field_validator("instructions")
    @classmethod
    def validate_instructions_word_count(cls, v: str | None) -> str | None:
        if v is not None and len(v.split()) > 300:
            raise ValueError("instructions must be at most 300 words")
        return v


class UpdateDutyTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    score_per_day: Decimal | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
    requirements: dict[str, Any] | None = None
    reserve_ratio: Decimal | None = Field(default=None, ge=0, le=1)
    reserve_minimum: int | None = Field(default=None, ge=0)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    start_time: time | None = None
    end_time: time | None = None
    instructions: str | None = Field(default=None)
    is_external: bool | None = None
    eligible_node_ids: list[uuid.UUID] | None = None

    @field_validator("instructions")
    @classmethod
    def validate_instructions_word_count(cls, v: str | None) -> str | None:
        if v is not None and len(v.split()) > 300:
            raise ValueError("instructions must be at most 300 words")
        return v


def _dt_out(d: DutyType) -> DutyTypeOut:
    return DutyTypeOut(
        id=d.id,
        name=d.name,
        score_per_day=d.score_per_day,
        description=d.description,
        active=d.active,
        requirements=d.requirements or {},
        reserve_ratio=d.reserve_ratio or Decimal("0.000"),
        reserve_minimum=d.reserve_minimum or 0,
        contact_name=d.contact_name,
        contact_phone=d.contact_phone,
        start_time=d.start_time,
        end_time=d.end_time,
        instructions=d.instructions,
        is_external=d.is_external,
        eligible_node_ids=d.eligible_node_ids,
    )


@router.get("/duty-types", response_model=list[DutyTypeOut])
def list_duty_types(
    session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)
) -> list[DutyTypeOut]:
    return [_dt_out(d) for d in session.execute(select(DutyType)).scalars().all()]


@router.post("/duty-types", response_model=DutyTypeOut, status_code=status.HTTP_201_CREATED)
def create_duty_type(
    body: CreateDutyTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> DutyTypeOut:
    try:
        dt = svc.create_duty_type(
            session,
            name=body.name,
            score_per_day=body.score_per_day,
            description=body.description,
            reserve_ratio=body.reserve_ratio,
            reserve_minimum=body.reserve_minimum,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            start_time=body.start_time,
            end_time=body.end_time,
            instructions=body.instructions,
            is_external=body.is_external,
            eligible_node_ids=body.eligible_node_ids,
            actor_id=user.id,
        )
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(dt)
    return _dt_out(dt)


@router.patch("/duty-types/{duty_type_id}", response_model=DutyTypeOut)
def update_duty_type(
    duty_type_id: uuid.UUID,
    body: UpdateDutyTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> DutyTypeOut:
    dt = session.get(DutyType, duty_type_id)
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        extra: dict = {}
        if "eligible_node_ids" in body.model_fields_set:
            extra["eligible_node_ids"] = body.eligible_node_ids
        svc.update_duty_type(
            session,
            duty_type=dt,
            name=body.name,
            score_per_day=body.score_per_day,
            description=body.description,
            actor_id=user.id,
            requirements=body.requirements,
            reserve_ratio=body.reserve_ratio,
            reserve_minimum=body.reserve_minimum,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            start_time=body.start_time,
            end_time=body.end_time,
            instructions=body.instructions,
            is_external=body.is_external,
            **extra,
        )
        if body.active is not None:
            svc.set_duty_type_active(session, duty_type=dt, active=body.active, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(dt)
    return _dt_out(dt)


class DutyTypeUsage(BaseModel):
    past_count: int
    future_count: int
    template_count: int
    shift_count: int
    exemption_map_count: int


@router.get("/duty-types/{duty_type_id}/usage", response_model=DutyTypeUsage)
def get_duty_type_usage(
    duty_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> DutyTypeUsage:
    today = date.today()
    past_count = session.execute(
        select(func.count(DutyAssignment.id)).where(
            DutyAssignment.duty_type_id == duty_type_id,
            DutyAssignment.status != "cancelled",
            DutyAssignment.end_date <= today,
        )
    ).scalar_one()
    future_count = session.execute(
        select(func.count(DutyAssignment.id)).where(
            DutyAssignment.duty_type_id == duty_type_id,
            DutyAssignment.status != "cancelled",
            DutyAssignment.end_date > today,
        )
    ).scalar_one()
    template_count = session.execute(
        select(func.count(ShiftTemplate.id)).where(
            ShiftTemplate.duty_type_id == duty_type_id
        )
    ).scalar_one()
    shift_count = session.execute(
        select(func.count(DutyShift.id)).where(
            DutyShift.duty_type_id == duty_type_id,
            DutyShift.status != "cancelled",
        )
    ).scalar_one()
    exemption_map_count = session.execute(
        select(func.count(ExemptionDutyTypeMap.duty_type_id)).where(
            ExemptionDutyTypeMap.duty_type_id == duty_type_id
        )
    ).scalar_one()
    return DutyTypeUsage(past_count=past_count, future_count=future_count, template_count=template_count, shift_count=shift_count, exemption_map_count=exemption_map_count)


@router.delete("/duty-types/{duty_type_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_duty_type(
    duty_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> None:
    dt = session.get(DutyType, duty_type_id)
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    shift_count = session.execute(
        select(DutyShift).where(DutyShift.duty_type_id == duty_type_id).limit(1)
    ).scalar_one_or_none()
    assignment_count = session.execute(
        select(DutyAssignment).where(DutyAssignment.duty_type_id == duty_type_id).limit(1)
    ).scalar_one_or_none()
    template_count = session.execute(
        select(ShiftTemplate).where(ShiftTemplate.duty_type_id == duty_type_id).limit(1)
    ).scalar_one_or_none()
    if shift_count or assignment_count or template_count:
        parts = []
        if shift_count:
            parts.append("משמרות")
        if assignment_count:
            parts.append("שיבוצים")
        if template_count:
            parts.append("תבניות")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"לא ניתן למחוק: קיימים {', '.join(parts)} עם סוג תורנות זה",
        )
    session.delete(dt)
    session.commit()


# ---- locations ----
class LocationOut(BaseModel):
    id: uuid.UUID
    name: str
    base: str | None
    active: bool


class CreateLocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base: str | None = Field(default=None, max_length=200)


class UpdateLocationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base: str | None = Field(default=None, max_length=200)
    active: bool | None = None


def _loc_out(loc: DutyLocation) -> LocationOut:
    return LocationOut(id=loc.id, name=loc.name, base=loc.base, active=loc.active)


@router.get("/locations", response_model=list[LocationOut])
def list_locations(
    session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)
) -> list[LocationOut]:
    return [_loc_out(loc) for loc in session.execute(select(DutyLocation)).scalars().all()]


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_location(
    body: CreateLocationRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> LocationOut:
    loc = svc.create_location(session, name=body.name, base=body.base, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _loc_out(loc)


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(
    location_id: uuid.UUID,
    body: UpdateLocationRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> LocationOut:
    loc = session.get(DutyLocation, location_id)
    if loc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.update_location(session, location=loc, name=body.name, base=body.base, actor_id=user.id)
    if body.active is not None:
        svc.set_location_active(session, location=loc, active=body.active, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _loc_out(loc)


# ---- exemption types + map ----
class ExemptionTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_global: bool = False
    is_medical: bool = False
    is_commander_exemption: bool = False
    active: bool = True


class CreateExemptionTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_global: bool = False
    is_medical: bool = False
    is_commander_exemption: bool = False


class UpdateExemptionTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_global: bool | None = None
    is_medical: bool | None = None
    is_commander_exemption: bool | None = None
    active: bool | None = None


class SetDutyTypesRequest(BaseModel):
    duty_type_ids: list[uuid.UUID]


def _et_out(et: ExemptionType) -> ExemptionTypeOut:
    return ExemptionTypeOut(
        id=et.id,
        name=et.name,
        description=et.description,
        is_global=et.is_global,
        is_medical=et.is_medical,
        is_commander_exemption=et.is_commander_exemption,
        active=et.active,
    )


@router.get("/exemption-types", response_model=list[ExemptionTypeOut])
def list_exemption_types(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[ExemptionTypeOut]:
    # Reference data: any authenticated (password-changed) user may list exemption-type
    # names, because commanders need them to fill the grant form. Mutations stay gated.
    return [_et_out(et) for et in session.execute(select(ExemptionType)).scalars().all()]


@router.post(
    "/exemption-types", response_model=ExemptionTypeOut, status_code=status.HTTP_201_CREATED
)
def create_exemption_type(
    body: CreateExemptionTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> ExemptionTypeOut:
    try:
        et = svc.create_exemption_type(
            session,
            name=body.name,
            description=body.description,
            is_global=body.is_global,
            is_medical=body.is_medical,
            is_commander_exemption=body.is_commander_exemption,
            actor_id=user.id,
        )
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(et)
    return _et_out(et)


@router.patch("/exemption-types/{exemption_type_id}", response_model=ExemptionTypeOut)
def update_exemption_type(
    exemption_type_id: uuid.UUID,
    body: UpdateExemptionTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> ExemptionTypeOut:
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.update_exemption_type(
            session,
            exemption_type=et,
            name=body.name,
            description=body.description,
            is_global=body.is_global,
            is_medical=body.is_medical,
            is_commander_exemption=body.is_commander_exemption,
            active=body.active,
            actor_id=user.id,
        )
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(et)
    return _et_out(et)


class DisableExemptionTypeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class DisableExemptionTypeOut(BaseModel):
    revoked_count: int


@router.post("/exemption-types/{exemption_type_id}/disable", response_model=DisableExemptionTypeOut)
def disable_exemption_type_route(
    exemption_type_id: uuid.UUID,
    body: DisableExemptionTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> DisableExemptionTypeOut:
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    revoked_count = svc.disable_exemption_type_and_revoke_all(
        session, exemption_type=et, reason=body.reason, actor_id=user.id,
    )
    session.commit()
    return DisableExemptionTypeOut(revoked_count=revoked_count)


@router.delete("/exemption-types/{exemption_type_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_exemption_type(
    exemption_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> None:
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.delete_exemption_type(session, exemption_type=et, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


@router.get("/exemption-types/duty-type-map", response_model=dict[str, list[str]])
def get_all_exemption_duty_type_maps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, list[str]]:
    """Return {exemption_type_id: [duty_type_id, ...]} for all exemption types in one query."""
    rows = session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all()
    result: dict[str, list[str]] = {}
    for etid, dtid in rows:
        result.setdefault(str(etid), []).append(str(dtid))
    return result


@router.get("/exemption-types/{exemption_type_id}/duty-types", response_model=list[uuid.UUID])
def get_exemption_duty_types(
    exemption_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> list[uuid.UUID]:
    return svc.list_exemption_duty_type_ids(session, exemption_type_id=exemption_type_id)


@router.put("/exemption-types/{exemption_type_id}/duty-types", response_model=list[uuid.UUID])
def put_exemption_duty_types(
    exemption_type_id: uuid.UUID,
    body: SetDutyTypesRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> list[uuid.UUID]:
    try:
        svc.set_exemption_duty_types(
            session,
            exemption_type_id=exemption_type_id,
            duty_type_ids=body.duty_type_ids,
            actor_id=user.id,
        )
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return svc.list_exemption_duty_type_ids(session, exemption_type_id=exemption_type_id)
