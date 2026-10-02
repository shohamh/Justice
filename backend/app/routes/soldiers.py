from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, exists, func, or_, select, text as sql_text, true
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
from app.auth.password import verify_password
from app.db.models import (
    DutyAssignment,
    DutyType,
    HierarchyNode,
    Soldier,
    SoldierFieldUpdate,
    TelegramLink,
)
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
from app.services.authority import (
    RankAdvancementEditScope,
    can_view_soldier_scope,
    rank_advancement_edit_authorized,
)
from app.services.approval_scope import UnitJoinDateEditScope
from app.services.request_metadata import latest_activity, person_ref
from app.services.eligibility import ENLISTED_RANKS
from app.services.rank_advancement import OFFICER_ACADEMIC_LADDER, OFFICER_LADDER
from app.services.duty_history import get_duty_history
from app.services.reserves import get_current_reserve_stats
from app.services.settings_loader import SettingNotFound, get_setting
from app.settings import get_settings

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
    rank_track: str | None = None
    next_rank_date: date_type | None = None
    next_rank_date_overridden: bool = False
    can_edit_rank_advancement: bool = False
    can_request_unit_join_date: bool = False
    bahad1_graduate: bool = False
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: date_type | None = None
    enlistment_date: date_type | None = None
    unit_join_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None
    food_type: str | None = None
    food_constraints: str | None = None
    telegram_linked: bool = False
    email: str | None = None
    direct_commander_id: uuid.UUID | None = None
    direct_commander_name: str | None = None
    visibility: str = "full"
    hierarchy_path: list[str] = Field(default_factory=list)


class SoldierRosterItem(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    left_at: date_type | None
    telegram_linked: bool
    is_commander: bool = False
    commander_node_name: str | None = None
    hierarchy_path: list[str] = Field(default_factory=list)


class SoldierRosterPage(BaseModel):
    items: list[SoldierRosterItem]
    next_cursor: str | None
    has_more: bool


class HakpazaRosterItem(BaseModel):
    id: uuid.UUID
    full_name: str
    rank: str | None
    next_shift_date: date_type | None
    next_shift_type_name: str | None


class HakpazaRosterPage(BaseModel):
    items: list[HakpazaRosterItem]
    next_cursor: str | None
    has_more: bool


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
    enrolled_at: date_type | None = None


class UpdateProfileRequest(BaseModel):
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    rank_track: str | None = None
    bahad1_graduate: bool | None = None
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None
    email: str | None = None
    food_type: Literal["regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin"] | None = None
    food_constraints: str | None = Field(default=None, max_length=2000)
    next_rank_date: date_type | None = None
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: date_type | None = None
    profile_picture_url: str | None = None


class PromoteAdminRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    confirm: Literal[True]


class FieldUpdateRequest(BaseModel):
    field_name: str
    new_value: str


class FieldUpdateDecisionRequest(BaseModel):
    decision_note: str | None = None


class NearestApproverOut(BaseModel):
    id: uuid.UUID
    name: str


class PersonRefOut(BaseModel):
    soldier_id: uuid.UUID
    name: str


class WaitingOnOut(BaseModel):
    kind: str  # "commander" | "duty_manager"
    soldier_id: uuid.UUID
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
    decided_by: PersonRefOut | None = None
    decided_at: Any
    decision_note: str | None
    created_at: Any
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None
    can_approve: bool = True
    requested_at: Any | None = None
    updated_at: Any | None = None
    waiting_on: WaitingOnOut | None = None
    commander_approved_by: PersonRefOut | None = None
    commander_approved_at: Any | None = None
    commander_approval_note: str | None = None
    duty_manager_approved_by: PersonRefOut | None = None
    duty_manager_approved_at: Any | None = None


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
    session: Session,
    user: Soldier,
    include_private: bool = False,
    telegram_linked: bool = False,
    direct_commander: Soldier | None = None,
    phone_public: bool = True,
    email_public: bool = True,
    rank_scope: RankAdvancementEditScope | None = None,
    unit_join_date_scope: UnitJoinDateEditScope | None = None,
    visibility: str = "full",
    include_hierarchy_path: bool = False,
) -> SoldierOut:
    public_mode = visibility == "public"
    hierarchy_path: list[str] = []
    if include_hierarchy_path:
        node = _node_of(session, s)
        if node is not None:
            named_nodes = {
                n.id: n.name
                for n in session.execute(
                    select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
                ).scalars()
            }
            hierarchy_path = [named_nodes[node_id] for node_id in node.path_ids if node_id in named_nodes]
    can_edit_rank_advancement = (
        rank_scope.authorized(_node_of(session, s))
        if rank_scope is not None
        else rank_advancement_edit_authorized(session, user=user, target_node=_node_of(session, s))
    )
    from app.services.approval_scope import unit_join_date_initiator_authorized
    can_request_unit_join_date = (
        not public_mode
        and (
            unit_join_date_scope.authorized(actor=user, target=s, target_node=_node_of(session, s))
            if unit_join_date_scope is not None
            else unit_join_date_initiator_authorized(session, actor=user, target=s)
        )
        and s.enrolled_at is not None
        and s.left_at is None
    )
    return SoldierOut(
        id=s.id,
        personal_number=s.personal_number,
        full_name=s.full_name,
        role=s.role,
        hierarchy_node_id=None if public_mode else s.hierarchy_node_id,
        phone=s.phone if (include_private or phone_public) else None,
        must_change_password=False if public_mode else s.must_change_password,
        left_at=None if public_mode else (s.left_at.isoformat() if s.left_at else None),
        enrolled_at=s.enrolled_at,
        gender=s.gender if (include_private and not public_mode) else None,
        is_officer=s.is_officer,
        is_career=s.is_career,
        rank=s.rank,
        rank_track=None if public_mode else s.rank_track,
        next_rank_date=s.next_rank_date,
        next_rank_date_overridden=False if public_mode else s.next_rank_date_overridden,
        can_edit_rank_advancement=False if public_mode else can_edit_rank_advancement,
        can_request_unit_join_date=can_request_unit_join_date,
        bahad1_graduate=s.bahad1_graduate,
        has_military_driving_license=None if public_mode else s.has_military_driving_license,
        military_driving_license_expiry=None if public_mode else s.military_driving_license_expiry,
        enlistment_date=s.enlistment_date,
        unit_join_date=s.unit_join_date,
        mandatory_end_date=s.mandatory_end_date,
        discharge_date=s.discharge_date,
        last_mitvahim_date=None if public_mode else s.last_mitvahim_date,
        last_alal_date=None if public_mode else s.last_alal_date,
        food_type=s.food_type if include_private else None,
        food_constraints=s.food_constraints if include_private else None,
        profile_picture_url=s.profile_picture_url,
        telegram_linked=False if public_mode else telegram_linked,
        email=s.email if (include_private or email_public) else None,
        visibility=visibility,
        hierarchy_path=hierarchy_path,
    )


def _fu_out(
    session: Session,
    u: SoldierFieldUpdate, soldier_name: str = "", node_name: str | None = None, include_values: bool = True,
    nearest_commander: NearestApproverOut | None = None, nearest_duty_manager: NearestApproverOut | None = None,
    can_approve: bool = True,
) -> FieldUpdateOut:
    if u.field_name == "unit_join_date":
        from app.services.approval_scope import nearest_unit_join_date_approver
        cmd_id = nearest_unit_join_date_approver(session, u.soldier_id, stage="commander")
        dm_id = nearest_unit_join_date_approver(session, u.soldier_id, stage="duty_manager")
        cmd = session.get(Soldier, cmd_id) if cmd_id else None
        dm = session.get(Soldier, dm_id) if dm_id else None
        nearest_commander = NearestApproverOut(id=cmd.id, name=cmd.full_name) if cmd else None
        nearest_duty_manager = NearestApproverOut(id=dm.id, name=dm.full_name) if dm else None
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
        decided_by=person_ref(session, u.decided_by),
        decided_at=u.decided_at,
        decision_note=u.decision_note,
        created_at=u.created_at,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve=can_approve,
        requested_at=u.created_at,
        updated_at=latest_activity(u.created_at, u.decided_at, u.commander_approved_at, u.duty_manager_approved_at),
        waiting_on=(
            WaitingOnOut(
                kind="commander", soldier_id=nearest_commander.id, name=nearest_commander.name,
            ) if u.status == "pending_commander" and nearest_commander else
            WaitingOnOut(
                kind="duty_manager", soldier_id=nearest_duty_manager.id, name=nearest_duty_manager.name,
            ) if u.status == "pending_duty_manager" and nearest_duty_manager else None
        ),
        commander_approved_by=person_ref(session, u.commander_approved_by),
        commander_approved_at=u.commander_approved_at,
        commander_approval_note=u.commander_approval_note,
        duty_manager_approved_by=person_ref(session, u.duty_manager_approved_by),
        duty_manager_approved_at=u.duty_manager_approved_at,
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


def _authorize_field_update_decision(
    session: Session, user: Soldier, s: Soldier, field_name: str, *, is_approval: bool,
) -> None:
    """Guards approve/reject on a pending field update.

    The rank-advancement authority requirement only applies to *approving* a
    rank/track/next-rank-date change — the plan restricts editing those
    fields to מדור-and-above actors, but rejecting a pending request isn't an
    edit, it's a no-op refusal. A lower-level commander/duty-manager who is
    otherwise authorized to manage the soldier must still be able to dismiss
    a bogus rank-change request, so reject always falls through to the
    generic field-update authorization below.
    """
    target_node = _node_of(session, s)
    if is_approval and field_name in {"rank", "rank_track", "is_officer", "next_rank_date"}:
        if not rank_advancement_edit_authorized(session, user=user, target_node=target_node):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return
    action = Action.MILITARY_LICENSE_DECIDE if field_name == "military_driving_license" else Action.SOLDIER_UPDATE
    authorize(session, user, action, target_node=target_node)


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
    return OnboardResponse(**_out(result.soldier, session=session, user=user, include_private=True).model_dump(), temp_password=result.temp_password)


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
    # Hoisted once per request (not per soldier) — rank_scope precomputes the
    # actor's commander/DM scope roots and מדור level rank a single time
    # instead of re-querying them for every soldier in the roster.
    rank_scope = RankAdvancementEditScope(session, user=user)
    unit_join_date_scope = UnitJoinDateEditScope(session, actor=user)
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        return [
            _out(s, session=session, user=user, include_private=False, telegram_linked=s.id in linked_ids, phone_public=phone_public, email_public=email_public, rank_scope=rank_scope, unit_join_date_scope=unit_join_date_scope)
            for s in rows
        ]

    roots = scope_root_ids(session, user)
    # Unassigned soldiers with no scope can only see themselves
    if not roots:
        return [_out(user, session=session, user=user, include_private=True, telegram_linked=user.id in linked_ids, rank_scope=rank_scope, unit_join_date_scope=unit_join_date_scope)]

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
        out.append(_out(s, session=session, user=user, include_private=include_private, telegram_linked=s.id in linked_ids, phone_public=phone_public, email_public=email_public, rank_scope=rank_scope, unit_join_date_scope=unit_join_date_scope))
    return out


class SoldierNamesRequest(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)


class SoldierNameOut(BaseModel):
    id: uuid.UUID
    full_name: str
    personal_number: str | None = None


@router.post("/lookup/names", response_model=list[SoldierNameOut], response_model_exclude_none=True)
def lookup_soldier_names(
    body: SoldierNamesRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SoldierNameOut]:
    # A scoped caller may resolve public names globally, but personal numbers
    # follow the private visibility boundary used by the soldier list.
    ids = list(dict.fromkeys(body.ids))
    roots = scope_root_ids(session, user)
    if not ids:
        return []
    if user.role != "admin" and not roots:
        ids = [soldier_id for soldier_id in ids if soldier_id == user.id]
    if not ids:
        return []
    rows = session.execute(
        select(Soldier.id, Soldier.full_name, Soldier.personal_number, Soldier.hierarchy_node_id)
        .where(Soldier.id.in_(ids))
    ).all()
    node_ids = {node_id for _, _, _, node_id in rows if node_id is not None}
    nodes = {
        node.id: node for node in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
        ).scalars().all()
    } if node_ids else {}
    names = {
        soldier_id: (
            name,
            personal_number if soldier_id == user.id or (
                (node := nodes.get(node_id)) is not None
                and any(root in node.path_ids for root in roots)
            ) else None,
        )
        for soldier_id, name, personal_number, node_id in rows
    }
    return [
        SoldierNameOut(id=soldier_id, full_name=names[soldier_id][0], personal_number=names[soldier_id][1])
        for soldier_id in ids
        if soldier_id in names
    ]


def _roster_cursor_binding(
    *, user: Soldier, roots: set[uuid.UUID], search: str, node: HierarchyNode | None,
    sort: str, descending: bool, active_only: bool, direct_node_only: bool, page_size: int,
    role_order: tuple[str, ...],
) -> str:
    # Recomputed for every request so a change in the caller's scope invalidates
    # the cursor before any rows are read.
    query = {
        "actor_id": str(user.id),
        "actor_role": user.role,
        "actor_node_id": str(user.hierarchy_node_id) if user.hierarchy_node_id else None,
        "scope_roots": sorted(str(root) for root in roots),
        "search": search,
        "node_id": str(node.id) if node else None,
        "node_path": [str(part) for part in node.path_ids] if node else None,
        "sort": sort,
        "role_order": role_order,
        "descending": descending,
        "active_only": active_only,
        "direct_node_only": direct_node_only,
        "page_size": page_size,
    }
    return hashlib.sha256(json.dumps(query, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _roster_revision(session: Session) -> int:
    return session.execute(
        sql_text("SELECT revision FROM soldier_roster_revision WHERE singleton = TRUE")
    ).scalar_one()


def _decode_roster_cursor(cursor: str, binding: str, revision: int) -> tuple[str | int, uuid.UUID]:
    settings = get_settings()
    try:
        payload = jwt.decode(cursor, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if (
            payload.get("purpose") != "soldier_roster"
            or payload.get("version") != 1
            or payload.get("binding") != binding
            or not isinstance(payload.get("key"), (str, int))
            or isinstance(payload.get("key"), bool)
            or not isinstance(payload.get("id"), str)
        ):
            raise ValueError("cursor_mismatch")
        if type(payload.get("revision")) is not int:
            raise ValueError("invalid_revision")
        if payload["revision"] != revision:
            raise HTTPException(status_code=409, detail="stale_cursor")
        return payload["key"], uuid.UUID(payload["id"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="invalid_cursor") from exc


@router.get("/roster", response_model=SoldierRosterPage)
def list_soldier_roster(
    search: str = Query(default="", max_length=200),
    node_id: uuid.UUID | None = None,
    direct_node_only: bool = False,
    active_only: bool = False,
    sort: Literal["full_name", "personal_number", "role", "node", "telegram"] = "full_name",
    role_order: str | None = Query(default=None, max_length=100),
    descending: bool = False,
    page_size: int = Query(default=100, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierRosterPage:
    """Public roster projection with SQL filters and stable keyset pagination."""
    roots = scope_root_ids(session, user) if user.role != "admin" else set()
    node = session.get(HierarchyNode, node_id) if node_id else None
    if node_id and node is None:
        raise HTTPException(status_code=404, detail="not_found")

    roles = tuple(part.strip() for part in role_order.split(",")) if role_order else ()
    valid_roles = {"admin", "commander", "duty_manager", "soldier"}
    if (role_order is not None and (len(roles) != 4 or set(roles) != valid_roles)) or (sort == "role" and not roles):
        raise HTTPException(status_code=400, detail="invalid_role_order")
    normalized_search = search.strip().casefold()
    binding = _roster_cursor_binding(
        user=user, roots=roots, search=normalized_search, node=node,
        sort=sort, descending=descending, active_only=active_only, page_size=page_size,
        direct_node_only=direct_node_only,
        role_order=roles,
    )
    revision = _roster_revision(session)
    last_key, last_id = _decode_roster_cursor(cursor, binding, revision) if cursor else (None, None)

    telegram_verified = exists(select(TelegramLink.soldier_id).where(
        TelegramLink.soldier_id == Soldier.id, TelegramLink.is_verified.is_(True),
    ))
    sort_columns = {
        "full_name": func.lower(Soldier.full_name),
        "personal_number": func.lower(Soldier.personal_number),
        "node": func.lower(func.coalesce(HierarchyNode.name, "")),
        "telegram": case((telegram_verified, "0"), else_="1"),
    }
    sort_key = (
        case(*[(Soldier.role == role, index) for index, role in enumerate(roles)], else_=4)
        if sort == "role" else sort_columns[sort]
    )
    statement = select(
        Soldier.id, Soldier.personal_number, Soldier.full_name, Soldier.role,
        Soldier.hierarchy_node_id, Soldier.left_at, sort_key.label("sort_key"),
        exists(
            select(HierarchyNode.id)
            .where(HierarchyNode.commander_id == Soldier.id)
            .correlate(Soldier)
        ).label("is_commander"),
        select(HierarchyNode.name)
        .where(HierarchyNode.commander_id == Soldier.id)
        .correlate(Soldier)
        .order_by(HierarchyNode.name, HierarchyNode.id)
        .limit(1)
        .scalar_subquery()
        .label("commander_node_name"),
    )
    if sort == "node" or normalized_search:
        statement = statement.outerjoin(HierarchyNode, HierarchyNode.id == Soldier.hierarchy_node_id)
    # GET /soldiers exposes public rows globally when the caller has a scope
    # root; an unscoped caller sees only themselves. The selected node can only
    # narrow this same visible set, including its descendant subtree.
    if user.role != "admin" and not roots:
        statement = statement.where(Soldier.id == user.id)
    if node_id:
        if direct_node_only:
            statement = statement.where(Soldier.hierarchy_node_id == node_id)
        else:
            statement = statement.where(
                Soldier.hierarchy_node_id.in_(
                    select(HierarchyNode.id).where(HierarchyNode.path_ids.contains([node_id]))
                )
            )
    if active_only:
        statement = statement.where(Soldier.left_at.is_(None))
    if normalized_search:
        escaped_search = normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_search}%"
        statement = statement.where(or_(
            Soldier.full_name.ilike(pattern, escape="\\"),
            Soldier.personal_number.ilike(pattern, escape="\\"),
            HierarchyNode.name.ilike(pattern, escape="\\"),
        ))
    if last_key is not None and last_id is not None:
        compare = sort_key < last_key if descending else sort_key > last_key
        compare_id = Soldier.id < last_id if descending else Soldier.id > last_id
        statement = statement.where(or_(compare, and_(sort_key == last_key, compare_id)))
    order = sort_key.desc() if descending else sort_key.asc()
    id_order = Soldier.id.desc() if descending else Soldier.id.asc()
    rows = session.execute(statement.order_by(order, id_order).limit(page_size + 1)).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    linked_ids: set[uuid.UUID] = set()
    if rows:
        linked_ids = set(session.execute(
            select(TelegramLink.soldier_id).where(
                TelegramLink.is_verified.is_(True),
                TelegramLink.soldier_id.in_([row.id for row in rows]),
            )
        ).scalars())
    page_node_ids = {row.hierarchy_node_id for row in rows if row.hierarchy_node_id}
    nodes_by_id = (
        {
            node.id: node
            for node in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(page_node_ids))
            ).scalars().all()
        }
        if page_node_ids
        else {}
    )
    path_node_ids = {
        path_id
        for node in nodes_by_id.values()
        for path_id in (node.path_ids or [node.id])
    }
    names_by_node_id = (
        dict(session.execute(
            select(HierarchyNode.id, HierarchyNode.name).where(HierarchyNode.id.in_(path_node_ids))
        ).all())
        if path_node_ids
        else {}
    )
    hierarchy_paths_by_node = {
        node_id: [
            names_by_node_id[path_id]
            for path_id in (node.path_ids or [node.id])
            if path_id in names_by_node_id
        ]
        for node_id, node in nodes_by_id.items()
    }
    if _roster_revision(session) != revision:
        raise HTTPException(status_code=409, detail="roster_changed")
    items = [
        SoldierRosterItem(
            id=row.id, personal_number=row.personal_number, full_name=row.full_name,
            role=row.role, hierarchy_node_id=row.hierarchy_node_id,
            left_at=row.left_at, telegram_linked=row.id in linked_ids,
            is_commander=bool(row.is_commander),
            commander_node_name=row.commander_node_name,
            hierarchy_path=hierarchy_paths_by_node.get(row.hierarchy_node_id, []),
        )
        for row in rows
    ]
    next_cursor = None
    if has_more:
        settings = get_settings()
        last = rows[-1]
        next_cursor = jwt.encode(
            {
                "purpose": "soldier_roster", "version": 1, "binding": binding,
                "key": last.sort_key, "id": str(last.id), "revision": revision,
                "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            },
            settings.jwt_secret, algorithm=settings.jwt_algorithm,
        )
    return SoldierRosterPage(items=items, next_cursor=next_cursor, has_more=has_more)


def _hakpaza_roster_cursor_binding(
    *,
    user: Soldier,
    roots: set[uuid.UUID],
    search: str,
    as_of_date: date_type,
    page_size: int,
) -> str:
    query = {
        "actor_id": str(user.id),
        "actor_role": user.role,
        "actor_node_id": str(user.hierarchy_node_id) if user.hierarchy_node_id else None,
        "scope_roots": sorted(str(root) for root in roots),
        "search": search,
        "as_of_date": as_of_date.isoformat(),
        "sort": ["next_shift_date_asc_nulls_last", "full_name_asc", "soldier_id_asc"],
        "page_size": page_size,
    }
    return hashlib.sha256(
        json.dumps(query, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _decode_hakpaza_roster_cursor(
    cursor: str, binding: str, revision: int
) -> tuple[date_type | None, str, uuid.UUID]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            cursor, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if (
            payload.get("purpose") != "hakpaza_soldier_roster"
            or payload.get("version") != 1
            or payload.get("binding") != binding
            or not isinstance(payload.get("full_name"), str)
            or not isinstance(payload.get("id"), str)
        ):
            raise ValueError("cursor_mismatch")
        raw_date = payload.get("next_shift_date")
        if raw_date is not None and not isinstance(raw_date, str):
            raise ValueError("invalid_date")
        if type(payload.get("revision")) is not int:
            raise ValueError("invalid_revision")
        if payload["revision"] != revision:
            raise HTTPException(status_code=409, detail="stale_cursor")
        return (
            date_type.fromisoformat(raw_date) if raw_date is not None else None,
            payload["full_name"],
            uuid.UUID(payload["id"]),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="invalid_cursor") from exc


@router.get("/roster/hakpaza", response_model=HakpazaRosterPage)
def list_hakpaza_soldier_roster(
    search: str = Query(default="", max_length=200),
    as_of_date: date_type = Query(),
    page_size: int = Query(default=100, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> HakpazaRosterPage:
    """Compact, authorized Hakpaza picker rows with a global stable keyset order."""
    roots = scope_root_ids(session, user) if user.role != "admin" else set()
    binding = _hakpaza_roster_cursor_binding(
        user=user,
        roots=roots,
        search=search,
        as_of_date=as_of_date,
        page_size=page_size,
    )
    revision = _roster_revision(session)
    last_date, last_name, last_id = (
        _decode_hakpaza_roster_cursor(cursor, binding, revision)
        if cursor
        else (None, "", None)
    )

    next_assignment = (
        select(
            DutyAssignment.start_date.label("shift_date"),
            DutyAssignment.duty_type_id.label("duty_type_id"),
        )
        .where(
            DutyAssignment.soldier_id == Soldier.id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= as_of_date,
        )
        .order_by(DutyAssignment.start_date.asc(), DutyAssignment.id.asc())
        .limit(1)
        .lateral("hakpaza_next_assignment")
    )
    shift_date = next_assignment.c.shift_date
    statement = (
        select(
            Soldier.id,
            Soldier.full_name,
            Soldier.rank,
            shift_date.label("next_shift_date"),
            DutyType.name.label("next_shift_type_name"),
        )
        .select_from(Soldier)
        .outerjoin(next_assignment, true())
        .outerjoin(DutyType, DutyType.id == next_assignment.c.duty_type_id)
    )
    # Keep the exact population returned by listSoldiers: admins and callers
    # with a scope root see the public roster; unscoped callers see themselves.
    if user.role != "admin" and not roots:
        statement = statement.where(Soldier.id == user.id)
    # Hakpaza historically uses case-sensitive String.includes on full_name.
    # Escape LIKE metacharacters so %, _ and backslash remain literal input.
    if search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            Soldier.full_name.like(f"%{escaped_search}%", escape="\\")
        )

    if last_id is not None:
        after_name = or_(
            Soldier.full_name > last_name,
            and_(Soldier.full_name == last_name, Soldier.id > last_id),
        )
        if last_date is None:
            statement = statement.where(shift_date.is_(None), after_name)
        else:
            statement = statement.where(
                or_(
                    shift_date > last_date,
                    and_(shift_date == last_date, after_name),
                    shift_date.is_(None),
                )
            )

    rows = session.execute(
        statement.order_by(
            case((shift_date.is_(None), 1), else_=0),
            shift_date.asc(),
            Soldier.full_name.asc(),
            Soldier.id.asc(),
        ).limit(page_size + 1)
    ).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    if _roster_revision(session) != revision:
        raise HTTPException(status_code=409, detail="roster_changed")

    items = [
        HakpazaRosterItem(
            id=row.id,
            full_name=row.full_name,
            rank=row.rank,
            next_shift_date=row.next_shift_date,
            next_shift_type_name=row.next_shift_type_name,
        )
        for row in rows
    ]
    next_cursor = None
    if has_more:
        settings = get_settings()
        last = rows[-1]
        next_cursor = jwt.encode(
            {
                "purpose": "hakpaza_soldier_roster",
                "version": 1,
                "binding": binding,
                "next_shift_date": (
                    last.next_shift_date.isoformat() if last.next_shift_date else None
                ),
                "full_name": last.full_name,
                "id": str(last.id),
                "revision": revision,
                "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    return HakpazaRosterPage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/lookup/personal-number", response_model=SoldierRosterItem | None)
def lookup_soldier_by_personal_number(
    personal_number: str = Query(min_length=1, max_length=20),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierRosterItem | None:
    """Exact-soldier lookup using the existing public roster visibility."""
    statement = select(Soldier).where(
        Soldier.personal_number == personal_number,
    )
    roots = scope_root_ids(session, user) if user.role != "admin" else set()
    if user.role != "admin" and not roots:
        statement = statement.where(Soldier.id == user.id)
    row = session.execute(statement.limit(1)).scalar_one_or_none()
    if row is None:
        return None
    linked = session.execute(
        select(TelegramLink.soldier_id).where(
            TelegramLink.soldier_id == row.id,
            TelegramLink.is_verified.is_(True),
        )
    ).scalar_one_or_none()
    node = session.get(HierarchyNode, row.hierarchy_node_id) if row.hierarchy_node_id else None
    hierarchy_path = []
    if node:
        path_names = dict(session.execute(
            select(HierarchyNode.id, HierarchyNode.name).where(
                HierarchyNode.id.in_(node.path_ids or [node.id])
            )
        ).all())
        hierarchy_path = [path_names[node_id] for node_id in (node.path_ids or [node.id]) if node_id in path_names]
    is_commander = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.commander_id == row.id).limit(1)
    ).first() is not None
    commander_node_name = session.execute(
        select(HierarchyNode.name)
        .where(HierarchyNode.commander_id == row.id)
        .order_by(HierarchyNode.name, HierarchyNode.id)
        .limit(1)
    ).scalar_one_or_none()
    return SoldierRosterItem(
        id=row.id,
        personal_number=row.personal_number,
        full_name=row.full_name,
        role=row.role,
        hierarchy_node_id=row.hierarchy_node_id,
        left_at=row.left_at,
        telegram_linked=linked is not None,
        is_commander=is_commander,
        commander_node_name=commander_node_name,
        hierarchy_path=hierarchy_path,
    )


def _field_update_can_approve(
    session: Session, *, user: Soldier, roots: set[uuid.UUID], is_cmd: bool, is_dm: bool,
    node: HierarchyNode | None, field_name: str, status: str = "pending",
) -> bool:
    """Shared by list_all_pending_field_updates and count_pending_field_updates so
    the nav badge's count always matches which cards actually show an approve
    button — a stale duplicate here would silently drift the two out of sync."""
    if field_name == "unit_join_date":
        if status not in {"pending_commander", "pending_duty_manager"}:
            return False
        from app.services.approval_scope import unit_join_date_stage_authorized
        stage = "commander" if status == "pending_commander" else "duty_manager"
        return unit_join_date_stage_authorized(session, actor=user, target_node=node, stage=stage)
    if field_name in {"rank", "rank_track", "is_officer", "next_rank_date"}:
        return rank_advancement_edit_authorized(session, user=user, target_node=node)
    decide_action = Action.MILITARY_LICENSE_DECIDE if field_name == "military_driving_license" else Action.SOLDIER_UPDATE
    return can(user, decide_action, target_node=node, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


# NOTE: /ranks, /field-updates/pending, and /{soldier_id}/duty-history MUST come before /{soldier_id} routes
@router.get("/ranks")
def get_ranks(_user: Soldier = Depends(require_password_changed)) -> dict[str, list[str]]:
    return {"enlisted": ENLISTED_RANKS, "officers": OFFICER_LADDER, "officer_academic": OFFICER_ACADEMIC_LADDER}


@router.get("/field-updates/pending", response_model=list[FieldUpdateOut])
def list_all_pending_field_updates(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    """Returns pending field updates for soldiers in the caller's scope."""
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(
            SoldierFieldUpdate.status.in_(("pending", "pending_commander", "pending_duty_manager"))
        )
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
                    session, upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values,
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
                can_approve = _field_update_can_approve(
                    session, user=user, roots=roots, is_cmd=user_is_commander, is_dm=user_is_duty_manager,
                    node=node, field_name=upd.field_name, status=upd.status,
                )
                result.append(
                    _fu_out(
                        session, upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values,
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
            select(SoldierFieldUpdate).where(
                SoldierFieldUpdate.status.in_(("pending", "pending_commander", "pending_duty_manager"))
            )
        ).scalars().all()
        return {"count": len(rows)}
    roots = scope_root_ids(session, user)
    if not roots:
        return {"count": 0}
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(
            SoldierFieldUpdate.status.in_(("pending", "pending_commander", "pending_duty_manager"))
        )
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
            # Counting mere read-visibility (as opposed to _field_update_can_approve)
            # would overcount: a commander can see every field update in scope but
            # structurally can't act on most of them (Action.SOLDIER_UPDATE is
            # duty-manager-only) — that used to inflate this count, and the nav
            # badge it feeds, with cards the viewer could never approve.
            if _field_update_can_approve(
                session, user=user, roots=roots, is_cmd=user_is_commander, is_dm=user_is_duty_manager,
                node=node, field_name=upd.field_name, status=upd.status,
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

    if not is_self and not can_view_soldier_scope(session, user, _node_of(session, s)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

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
    target_node = _node_of(session, s)
    has_read_permission = is_self or can(
        user,
        Action.SOLDIER_READ,
        target_node=target_node,
        roots=scope_root_ids(session, user),
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    )
    # Soldiers, commanders, and duty managers without scope over this
    # soldier still get a redacted public profile instead of a 403 — _out()
    # strips every field outside the public allowlist when visibility is
    # "public" (see its `public_mode` gating).
    is_public_viewer = user.role in ("soldier", "commander", "duty_manager")
    if not has_read_permission and not is_public_viewer:
        authorize(session, user, Action.SOLDIER_READ, target_node=target_node)
    visibility = "full" if has_read_permission else "public"
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
        session=session,
        user=user,
        include_private=can_see_private(session, user, s),
        telegram_linked=link is not None,
        direct_commander=commander,
        phone_public=phone_public,
        email_public=email_public,
        visibility=visibility,
        include_hierarchy_path=True,
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
    svc.update_soldier(
        session, soldier=s, full_name=body.full_name, phone=body.phone, actor_id=user.id
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
    return _out(s, session=session, user=user, include_private=can_see_private(session, user, s), phone_public=phone_public, email_public=email_public)


@router.patch("/{soldier_id}/profile", response_model=SoldierOut)
def update_profile(
    soldier_id: uuid.UUID,
    body: UpdateProfileRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    target_node = _node_of(session, s)
    rank_advancement_fields = {"rank", "rank_track", "is_officer", "next_rank_date"}
    supplied_fields = body.model_fields_set
    supplied_rank_fields = rank_advancement_fields & supplied_fields
    supplied_ordinary_fields = supplied_fields - rank_advancement_fields

    # An ordinary profile save always resubmits the rank fields it displays,
    # even when the actor never touched them (the frontend's rankFieldsDirty
    # omission is only a "second line of defense" per its own comment, not
    # something this endpoint should rely on for authorization). Gate the
    # extra rank-advancement authority requirement on an actual value change,
    # not mere presence, so resubmitting unchanged rank data never wrongly
    # demands מדור-or-above authority from an otherwise-authorized editor —
    # mirrors the same fix applied to PATCH /enrollment-requests/{id}.
    def _rank_field_changed(field: str, raw: object, current: object) -> bool:
        if field == "rank":
            return (raw or None) != current
        if field == "is_officer":
            return bool(raw) != bool(current)
        return raw != current

    rank_fields_changed = any(
        _rank_field_changed(f, getattr(body, f), getattr(s, f)) for f in supplied_rank_fields
    )
    has_rank_authority = (
        rank_advancement_edit_authorized(session, user=user, target_node=target_node)
        if supplied_rank_fields else False
    )
    if rank_fields_changed and not has_rank_authority:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    if supplied_ordinary_fields or not supplied_rank_fields:
        authorize(session, user, Action.SOLDIER_UPDATE, target_node=target_node)
    elif not has_rank_authority:
        # Pure rank-only submission (no ordinary fields): even when nothing in
        # it actually changed, the caller must still hold rank-advancement
        # gate in that case, so it can't be skipped just because the values
        # happened to match what's already stored.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    nullable_fields = {"next_rank_date", "food_type", "food_constraints"}
    fields = {
        k: v for k, v in body.model_dump().items()
        if v is not None or (k in nullable_fields and k in supplied_fields)
    }
    try:
        update_soldier_profile(session, soldier=s, fields=fields, actor_id=user.id)
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(s)
    phone_public, email_public = _contact_visibility(session)
    return _out(s, session=session, user=user, include_private=can_see_private(session, user, s), phone_public=phone_public, email_public=email_public)


@router.post("/{soldier_id}/field-updates", response_model=FieldUpdateOut, status_code=201)
def create_field_update(
    soldier_id: uuid.UUID,
    body: FieldUpdateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    try:
        from app.services.approval_scope import unit_join_date_initiator_authorized
        if body.field_name == "unit_join_date" and not unit_join_date_initiator_authorized(session, actor=user, target=s):
            raise HTTPException(status_code=403, detail="forbidden")
        if body.field_name != "unit_join_date" and s.id != user.id:
            raise HTTPException(status_code=403, detail="forbidden")
        req = submit_field_update(
            session, soldier_id=soldier_id, field_name=body.field_name,
            new_value=body.new_value, actor_id=user.id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(req)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _fu_out(session, req, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


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
        _fu_out(session, r, include_values=include_values, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)
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
    if upd.field_name == "unit_join_date":
        from app.services.approval_scope import unit_join_date_stage_authorized
        stage = "commander" if upd.status == "pending_commander" else "duty_manager"
        if not unit_join_date_stage_authorized(session, actor=user, target_node=_node_of(session, s), stage=stage):
            raise HTTPException(status_code=403, detail="forbidden")
    else:
        _authorize_field_update_decision(session, user, s, upd.field_name, is_approval=True)
    try:
        approve_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _fu_out(
        session, upd, include_values=can_see_private(session, user, s),
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
    if upd.field_name == "unit_join_date":
        from app.services.approval_scope import unit_join_date_stage_authorized
        stage = "commander" if upd.status == "pending_commander" else "duty_manager"
        if not unit_join_date_stage_authorized(session, actor=user, target_node=_node_of(session, s), stage=stage):
            raise HTTPException(status_code=403, detail="forbidden")
    else:
        _authorize_field_update_decision(session, user, s, upd.field_name, is_approval=False)
    try:
        reject_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _fu_out(
        session, upd, include_values=can_see_private(session, user, s),
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


@router.post("/{soldier_id}/promote-admin", response_model=SoldierOut)
def promote_admin(
    soldier_id: uuid.UUID,
    body: PromoteAdminRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wrong_current_password")
    soldier = _load(session, soldier_id)
    svc.promote_to_admin(session, soldier=soldier, actor_id=user.id)
    session.commit()
    session.refresh(soldier)
    phone_public, email_public = _contact_visibility(session)
    return _out(
        soldier,
        session=session,
        user=user,
        include_private=can_see_private(session, user, soldier),
        phone_public=phone_public,
        email_public=email_public,
    )


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
