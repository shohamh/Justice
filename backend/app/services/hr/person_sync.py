from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import HrHierarchyNodeMap, Soldier, SoldierHrProfile
from app.services.hr.mapping import HeldForReview, MappedSoldierFields
from app.services.hr.schemas import HrUser
from app.services.settings_loader import SettingNotFound, get_setting

# Priority order for which org-unit id determines a person's placement.
# TODO: placeholder order, unconfirmed against real HR data — see design
# doc's "Open questions" section.
_PLACEMENT_ID_PRIORITY = ("team_id", "mador_id", "branch_id", "department_id", "shetach_id", "unit_id")


def _holding_node_id(session: Session) -> uuid.UUID:
    try:
        return uuid.UUID(get_setting(session, "system.holding_node_id"))
    except SettingNotFound as exc:
        raise RuntimeError("system.holding_node_id is not bootstrapped") from exc


def resolve_placement_node_id(session: Session, user: HrUser) -> uuid.UUID:
    for field_name in _PLACEMENT_ID_PRIORITY:
        group_id = getattr(user, field_name)
        if group_id is None:
            continue
        mapping = session.execute(
            select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == group_id)
        ).scalar_one_or_none()
        if mapping is not None:
            return mapping.node_id
    return _holding_node_id(session)


def _find_or_create_soldier_hr_profile(session: Session, personal_number: str) -> SoldierHrProfile:
    profile = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.personal_number == personal_number)
    ).scalar_one_or_none()
    if profile is None:
        profile = SoldierHrProfile(personal_number=personal_number, raw_dto={})
        session.add(profile)
        session.flush()
    return profile


def _apply_new_person(
    session: Session, user: HrUser, mapped: MappedSoldierFields,
) -> tuple[Soldier, SoldierHrProfile]:
    soldier = session.execute(
        select(Soldier).where(Soldier.personal_number == mapped.personal_number)
    ).scalar_one_or_none()

    if soldier is None:
        node_id = resolve_placement_node_id(session, user)
        soldier = Soldier(
            personal_number=mapped.personal_number,
            full_name=mapped.full_name,
            password_hash=hash_password(secrets.token_hex(16)),
            must_change_password=True,
            hierarchy_node_id=node_id,
            email=mapped.email,
            phone=mapped.phone,
            profile_picture_url=mapped.profile_picture_url,
            gender=mapped.gender,
            rank=mapped.rank,
            rank_track=mapped.rank_track,
            is_officer=mapped.is_officer,
            is_career=mapped.is_career,
            enlistment_date=mapped.enlistment_date,
            mandatory_end_date=mapped.mandatory_end_date,
            discharge_date=mapped.discharge_date,
        )
        session.add(soldier)
        session.flush()

    profile = _find_or_create_soldier_hr_profile(session, mapped.personal_number)
    profile.soldier_id = soldier.id
    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "synced"
    profile.review_reason = None
    profile.last_synced_at = datetime.now(tz=timezone.utc)
    return soldier, profile


def _mark_held(session: Session, user: HrUser, held: HeldForReview) -> SoldierHrProfile:
    profile = _find_or_create_soldier_hr_profile(session, held.personal_number)
    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "held_for_review"
    profile.review_reason = "; ".join(held.reasons)
    profile.last_synced_at = datetime.now(tz=timezone.utc)
    return profile
