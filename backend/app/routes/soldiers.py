from __future__ import annotations

import uuid
from datetime import date as date_type
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import (
    Action,
    authorize,
    can,
    can_see_private,
    is_commander,
    is_duty_manager,
    scope_root_ids,
    PRIVATE_FIELD_NAMES,
)
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier, SoldierFieldUpdate, TelegramLink
from app.db.session import get_session
from app.audit.writer import write_audit
from app.services import soldiers as svc
from app.services import scoring as scoring_svc
from app.services.soldiers import (
    approve_field_update,
    reject_field_update,
    submit_field_update,
    update_soldier_profile,
)
from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS
from app.services.duty_history import get_duty_history
from app.services.reserves import get_current_reserve_stats
from app.services.settings_loader import SettingNotFound, get_setting

router = APIRouter(prefix="/soldiers", tags=["soldiers"])


class SoldierOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    phone: str | None
    must_change_password: bool
    left_at: str | None
    enrolled_at: date_type | None = None
    # Profile fields
    gender: str | None = None
    is_officer: bool | None = None
    is_career: bool = False
    rank: str | None = None
    bahad1_graduate: bool = False
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: date_type | None = None
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None
    profile_picture_url: str | None = None
    telegram_linked: bool = False
    email: str | None = None
    direct_commander_id: uuid.UUID | None = None
    direct_commander_name: str | None = None


class OnboardRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=200)
    hierarchy_node_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=40)
    password: str | None = Field(default=None, max_length=200)


class OnboardResponse(SoldierOut):
    temp_password: str | None


class UpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    hierarchy_node_id: uuid.UUID | None = None
    enrolled_at: date_type | None = None


class UpdateProfileRequest(BaseModel):
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool | None = None
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None
    email: str | None = None
    profile_picture_url: str | None = None


class FieldUpdateRequest(BaseModel):
    field_name: str
    new_value: str


class FieldUpdateDecisionRequest(BaseModel):
    decision_note: str | None = None


class NearestApproverOut(BaseModel):
    id: uuid.UUID
    name: str


class FieldUpdateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    field_name: str
    previous_value: str | None
    new_value: str | None        # None when viewer cannot see private field values
    status: str
    decided_by: uuid.UUID | None
    decided_at: Any
    decision_note: str | None
    created_at: Any
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None
    can_approve: bool = True


class TimelineEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    date: str
    end_date: str | None
    title: str
    description: str | None
    status: str | None
    metadata: dict
    created_at: str


class SoldierScoreOut(BaseModel):
    soldier_id: uuid.UUID
    active_days: int
    cumulative_score: Decimal
    normalised_score: Decimal


def _direct_commander(session: Session, s: Soldier) -> Soldier | None:
    """Return the soldier's direct commander from the hierarchy, skipping self."""
    if s.hierarchy_node_id is None:
        return None
    node = session.get(HierarchyNode, s.hierarchy_node_id)
    if node is None:
        return None
    if node.commander_id and node.commander_id != s.id:
        return session.get(Soldier, node.commander_id)
    # Soldier is their own node's commander — go up one level
    if node.parent_id is None:
        return None
    parent = session.get(HierarchyNode, node.parent_id)
    if parent is None or parent.commander_id is None or parent.commander_id == s.id:
        return None
    return session.get(Soldier, parent.commander_id)



def _contact_visibility(session: Session) -> tuple[bool, bool]:
    """Returns (phone_public, email_public) — whether those two fields bypass
    the normal private-field scope check and are visible to anyone who can
    see the soldier's record at all. Both default to True when unset."""
    def _flag(key: str) -> bool:
        try:
            value = get_setting(session, key)
            return bool(value)
        except SettingNotFound:
            return True
    return _flag("soldiers.phone_public"), _flag("soldiers.email_public")


def _out(
    s: Soldier,
    *,
    include_private: bool = False,
    telegram_linked: bool = False,
    direct_commander: Soldier | None = None,
    phone_public: bool = True,
    email_public: bool = True,
) -> SoldierOut:
    return SoldierOut(
        id=s.id,
        personal_number=s.personal_number,
        full_name=s.full_name,
        role=s.role,
        hierarchy_node_id=s.hierarchy_node_id,
        phone=s.phone if (include_private or phone_public) else None,
        must_change_password=s.must_change_password,
        left_at=s.left_at.isoformat() if s.left_at else None,
        enrolled_at=s.enrolled_at,
        gender=s.gender if include_private else None,
        is_officer=s.is_officer,
        is_career=s.is_career,
        rank=s.rank,
        bahad1_graduate=s.bahad1_graduate,
        has_military_driving_license=s.has_military_driving_license,
        military_driving_license_expiry=s.military_driving_license_expiry,
        enlistment_date=s.enlistment_date,
        mandatory_end_date=s.mandatory_end_date,
        discharge_date=s.discharge_date,
        last_mitvahim_date=s.last_mitvahim_date,
        last_alal_date=s.last_alal_date,
        profile_picture_url=s.profile_picture_url,
        telegram_linked=telegram_linked,
        email=s.email if (include_private or email_public) else None,
        direct_commander_id=direct_commander.id if direct_commander else None,
        direct_commander_name=direct_commander.full_name if direct_commander else None,
    )


def _fu_out(
    u: SoldierFieldUpdate, soldier_name: str = "", node_name: str | None = None, include_values: bool = True,
    nearest_commander: NearestApproverOut | None = None, nearest_duty_manager: NearestApproverOut | None = None,
    can_approve: bool = True,
) -> FieldUpdateOut:
    redact = not include_values and u.field_name in PRIVATE_FIELD_NAMES
    return FieldUpdateOut(
        id=u.id,
        soldier_id=u.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        field_name=u.field_name,
        previous_value=None if redact else u.previous_value,
        new_value=None if redact else u.new_value,
        status=u.status,
        decided_by=u.decided_by,
        decided_at=u.decided_at,
        decision_note=u.decision_note,
        created_at=u.created_at,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve=can_approve,
    )


def _nearest_approvers(
    session: Session, soldier_id: uuid.UUID
) -> tuple[NearestApproverOut | None, NearestApproverOut | None]:
    from app.services.approval_scope import nearest_commander_for_soldier, nearest_duty_manager_for_soldier

    cmd_id = nearest_commander_for_soldier(session, soldier_id)
    dm_id = nearest_duty_manager_for_soldier(session, soldier_id)
    cmd = session.get(Soldier, cmd_id) if cmd_id else None
    dm = session.get(Soldier, dm_id) if dm_id else None
    return (
        NearestApproverOut(id=cmd.id, name=cmd.full_name) if cmd else None,
        NearestApproverOut(id=dm.id, name=dm.full_name) if dm else None,
    )


def _load(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _authorize_field_update_decision(session: Session, user: Soldier, s: Soldier, field_name: str) -> None:
    action = Action.MILITARY_LICENSE_DECIDE if field_name == "military_driving_license" else Action.SOLDIER_UPDATE
    authorize(session, user, action, target_node=_node_of(session, s))


@router.post("", response_model=OnboardResponse, status_code=status.HTTP_201_CREATED)
def onboard(
    body: OnboardRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> OnboardResponse:
    target_node = (
        session.get(HierarchyNode, body.hierarchy_node_id) if body.hierarchy_node_id else None
    )
    authorize(session, user, Action.SOLDIER_CREATE, target_node=target_node)
    try:
        result = svc.onboard_soldier(
            session,
            personal_number=body.personal_number,
            full_name=body.full_name,
            hierarchy_node_id=body.hierarchy_node_id,
            phone=body.phone,
            password=body.password,
            actor_id=user.id,
        )
    except svc.PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short"
        ) from exc
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(result.soldier)
    return OnboardResponse(**_out(result.soldier, include_private=True).model_dump(), temp_password=result.temp_password)


@router.get("", response_model=list[SoldierOut])
def list_soldiers(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[SoldierOut]:
    linked_ids: set[uuid.UUID] = {
        row for (row,) in session.execute(
            select(TelegramLink.soldier_id).where(TelegramLink.is_verified == True)
        ).all()
    }
    phone_public, email_public = _contact_visibility(session)
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        return [
            _out(s, include_private=False, telegram_linked=s.id in linked_ids, phone_public=phone_public, email_public=email_public)
            for s in rows
        ]

    roots = scope_root_ids(session, user)
    # Unassigned soldiers with no scope can only see themselves
    if not roots:
        return [_out(user, include_private=True, telegram_linked=user.id in linked_ids)]

    rows = session.execute(select(Soldier)).scalars().all()
    node_ids = {s.hierarchy_node_id for s in rows if s.hierarchy_node_id}
    nodes_by_id: dict[uuid.UUID, HierarchyNode] = {}
    if node_ids:
        nodes_by_id = {
            n.id: n for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }
    out: list[SoldierOut] = []
    for s in rows:
        node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        in_scope = node is not None and any(r in node.path_ids for r in roots)
        include_private = in_scope or s.id == user.id
        out.append(_out(s, include_private=include_private, telegram_linked=s.id in linked_ids, phone_public=phone_public, email_public=email_public))
    return out


# NOTE: /ranks, /field-updates/pending, and /{soldier_id}/duty-history MUST come before /{soldier_id} routes
@router.get("/ranks")
def get_ranks(_user: Soldier = Depends(require_password_changed)) -> dict[str, list[str]]:
    return {"enlisted": ENLISTED_RANKS, "officers": OFFICER_RANKS}


@router.get("/field-updates/pending", response_model=list[FieldUpdateOut])
def list_all_pending_field_updates(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    """Returns pending field updates for soldiers in the caller's scope."""
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
    ).scalars().all()
    if not all_pending:
        return []
    soldier_ids = {upd.soldier_id for upd in all_pending}
    soldiers_by_id = {
        s.id: s for s in session.execute(
            select(Soldier).where(Soldier.id.in_(soldier_ids))
        ).scalars().all()
    }
    node_ids = {s.hierarchy_node_id for s in soldiers_by_id.values() if s.hierarchy_node_id}
    nodes_by_id = {
        n.id: n for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
        ).scalars().all()
    } if node_ids else {}
    if user.role == "admin":
        result = []
        for upd in all_pending:
            s = soldiers_by_id.get(upd.soldier_id)
            soldier_name = s.full_name if s else str(upd.soldier_id)[:8]
            node_name = (
                nodes_by_id[s.hierarchy_node_id].name
                if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
                else None
            )
            include_values = s is not None and can_see_private(session, user, s)
            nearest_commander, nearest_duty_manager = _nearest_approvers(session, upd.soldier_id)
            result.append(
                _fu_out(
                    upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values,
                    nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                    can_approve=True,
                )
            )
        return result
    roots = scope_root_ids(session, user)
    if not roots:
        return []
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    result = []
    for upd in all_pending:
        s = soldiers_by_id.get(upd.soldier_id)
        if s:
            node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
            if can(
                user, Action.SOLDIER_READ, target_node=node, roots=roots,
                is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
            ):
                soldier_name = s.full_name
                node_name = node.name if node else None
                include_values = can_see_private(session, user, s)
                nearest_commander, nearest_duty_manager = _nearest_approvers(session, upd.soldier_id)
                decide_action = (
                    Action.MILITARY_LICENSE_DECIDE if upd.field_name == "military_driving_license" else Action.SOLDIER_UPDATE
                )
                can_approve = can(
                    user, decide_action, target_node=node, roots=roots,
                    is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
                )
                result.append(
                    _fu_out(
                        upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values,
                        nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
                        can_approve=can_approve,
                    )
                )
    return result


@router.get("/field-updates/pending/count")
def count_pending_field_updates(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    if user.role == "admin":
        rows = session.execute(
            select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
        ).scalars().all()
        return {"count": len(rows)}
    roots = scope_root_ids(session, user)
    if not roots:
        return {"count": 0}
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
    ).scalars().all()
    if not all_pending:
        return {"count": 0}
    soldier_ids = {upd.soldier_id for upd in all_pending}
    soldiers_by_id = {
        s.id: s for s in session.execute(
            select(Soldier).where(Soldier.id.in_(soldier_ids))
        ).scalars().all()
    }
    node_ids = {s.hierarchy_node_id for s in soldiers_by_id.values() if s.hierarchy_node_id}
    nodes_by_id = {
        n.id: n for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
        ).scalars().all()
    } if node_ids else {}
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    total = 0
    for upd in all_pending:
        s = soldiers_by_id.get(upd.soldier_id)
        if s:
            node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
            if can(
                user, Action.SOLDIER_READ, target_node=node, roots=roots,
                is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
            ):
                total += 1
    return {"count": total}


class ReserveStatsOut(BaseModel):
    used_days: int
    max_days: int
    window_days: int


@router.get("/me/reserve-stats", response_model=ReserveStatsOut)
def get_my_reserve_stats(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ReserveStatsOut:
    stats = get_current_reserve_stats(session, user.id)
    return ReserveStatsOut(**stats)


@router.get("/{soldier_id}/score", response_model=SoldierScoreOut)
def get_soldier_score(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    if s.id != user.id and user.role != "soldier":
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    ad = scoring_svc.active_days(session, soldier=s)
    cum = scoring_svc.cumulative_score(session, soldier_id=s.id)
    normalised = scoring_svc.normalised_score(session, soldier=s)
    return SoldierScoreOut(
        soldier_id=s.id,
        active_days=ad,
        cumulative_score=cum,
        normalised_score=normalised,
    )


_PUBLIC_EVENT_TYPES = {"assignment", "cancellation"}


@router.get("/{soldier_id}/duty-history", response_model=list[TimelineEventOut])
def get_soldier_duty_history(
    soldier_id: uuid.UUID,
    include_drafts: bool = Query(False),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    is_self = s.id == user.id
    is_plain_soldier = user.role == "soldier"

    if not is_self and not is_plain_soldier:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

    if include_drafts and user.role != "admin" and not is_duty_manager(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    include_sensitive = can_see_private(session, user, s)
    events = get_duty_history(
        session, soldier_id, include_drafts=include_drafts, include_sensitive=include_sensitive
    )

    if is_plain_soldier and not is_self:
        events = [e for e in events if e.event_type in _PUBLIC_EVENT_TYPES]

    return [
        TimelineEventOut(
            id=e.id,
            event_type=e.event_type,
            date=e.date,
            end_date=e.end_date,
            title=e.title,
            description=e.description,
            status=e.status,
            metadata=e.metadata,
            created_at=e.created_at,
        )
        for e in events
    ]


@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    is_self = s.id == user.id
    is_plain_soldier = user.role == "soldier"
    if not is_self and not is_plain_soldier:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier_id,
            TelegramLink.is_verified == True,
        )
    ).scalar_one_or_none()
    commander = _direct_commander(session, s)
    phone_public, email_public = _contact_visibility(session)
    return _out(
        s,
        include_private=can_see_private(session, user, s),
        telegram_linked=link is not None,
        direct_commander=commander,
        phone_public=phone_public,
        email_public=email_public,
    )


@router.patch("/{soldier_id}", response_model=SoldierOut)
def update(
    soldier_id: uuid.UUID,
    body: UpdateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    if body.hierarchy_node_id is not None and body.hierarchy_node_id != s.hierarchy_node_id:
        dest_node = session.get(HierarchyNode, body.hierarchy_node_id)
        if dest_node is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="destination_node_not_found")
        authorize(session, user, Action.SOLDIER_UPDATE, target_node=dest_node)
    svc.update_soldier(
        session, soldier=s, full_name=body.full_name, phone=body.phone,
        hierarchy_node_id=body.hierarchy_node_id, actor_id=user.id
    )
    if body.enrolled_at is not None:
        old_enrolled_at = s.enrolled_at
        s.enrolled_at = body.enrolled_at
        write_audit(
            session,
            actor_id=user.id,
            action="soldier.enrolled_at_update",
            entity_type="soldier",
            entity_id=s.id,
            before={"enrolled_at": old_enrolled_at.isoformat() if old_enrolled_at else None},
            after={"enrolled_at": body.enrolled_at.isoformat()},
        )
    session.commit()
    session.refresh(s)
    phone_public, email_public = _contact_visibility(session)
    return _out(s, include_private=can_see_private(session, user, s), phone_public=phone_public, email_public=email_public)


@router.patch("/{soldier_id}/profile", response_model=SoldierOut)
def update_profile(
    soldier_id: uuid.UUID,
    body: UpdateProfileRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    update_soldier_profile(session, soldier=s, fields=fields, actor_id=user.id)
    session.commit()
    session.refresh(s)
    phone_public, email_public = _contact_visibility(session)
    return _out(s, include_private=can_see_private(session, user, s), phone_public=phone_public, email_public=email_public)


@router.post("/{soldier_id}/field-updates", response_model=FieldUpdateOut, status_code=201)
def create_field_update(
    soldier_id: uuid.UUID,
    body: FieldUpdateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    if s.id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        req = submit_field_update(
            session, soldier_id=soldier_id, field_name=body.field_name,
            new_value=body.new_value, actor_id=user.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(req)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _fu_out(req, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


@router.get("/{soldier_id}/field-updates", response_model=list[FieldUpdateOut])
def list_field_updates(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    s = _load(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    rows = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.soldier_id == soldier_id)
        .order_by(SoldierFieldUpdate.created_at.desc())
    ).scalars().all()
    include_values = can_see_private(session, user, s)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return [
        _fu_out(r, include_values=include_values, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)
        for r in rows
    ]


@router.post("/{soldier_id}/field-updates/{update_id}/approve", response_model=FieldUpdateOut)
def approve_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    _authorize_field_update_decision(session, user, s, upd.field_name)
    try:
        approve_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _fu_out(
        upd, include_values=can_see_private(session, user, s),
        nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
    )


@router.post("/{soldier_id}/field-updates/{update_id}/reject", response_model=FieldUpdateOut)
def reject_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    _authorize_field_update_decision(session, user, s, upd.field_name)
    try:
        reject_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _fu_out(
        upd, include_values=can_see_private(session, user, s),
        nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
    )


@router.post("/{soldier_id}/reset-password")
def reset_password(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_RESET_PASSWORD, target_node=_node_of(session, s))
    temp = svc.reset_password(session, soldier=s, actor_id=user.id)
    session.commit()
    return {"temp_password": temp}


@router.delete("/{soldier_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete(
    soldier_id: uuid.UUID,
    left_at: date_type | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_DELETE, target_node=_node_of(session, s))
    svc.soft_delete(session, soldier=s, actor_id=user.id, left_at=left_at)
    session.commit()
