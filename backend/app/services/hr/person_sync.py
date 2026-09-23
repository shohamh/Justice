from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import (
    HrHierarchyNodeMap,
    HrPersonSync,
    HrPersonSyncError,
    NotificationType,
    Soldier,
    SoldierHrProfile,
)
from app.services.duty_eligibility_watch import recheck_soldier_assignments
from app.services.hr.client import HrApiClient
from app.services.hr.divergence import record_sync_divergence
from app.services.hr.mapping import HR_OWNED_FIELDS, HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.schemas import HrUser
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting
from app.services.soldiers import _reset_rank_advancement

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


_DEPENDENT_LOGIC_TRIGGER_FIELDS = frozenset({"rank", "mandatory_end_date", "discharge_date"})


def _apply_existing_person(
    session: Session, profile: SoldierHrProfile, user: HrUser, mapped: MappedSoldierFields,
) -> None:
    soldier = session.get(Soldier, profile.soldier_id)
    changed_dependent_field = False

    for field_name in HR_OWNED_FIELDS:
        if field_name == "personal_number":
            continue
        new_value = getattr(mapped, field_name)
        if field_name in profile.overridden_fields:
            old_value = getattr(soldier, field_name)
            if old_value != new_value:
                record_sync_divergence(
                    session, soldier_hr_profile_id=profile.id, field_name=field_name,
                    hr_value=new_value, local_value=old_value,
                )
            continue
        old_value = getattr(soldier, field_name)
        if field_name in _DEPENDENT_LOGIC_TRIGGER_FIELDS and old_value != new_value:
            changed_dependent_field = True
        setattr(soldier, field_name, new_value)

    soldier.is_officer = mapped.is_officer
    soldier.is_career = mapped.is_career

    if changed_dependent_field:
        _reset_rank_advancement(session, soldier, since=date.today())
        recheck_soldier_assignments(session, soldier.id)

    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "synced"
    profile.last_synced_at = datetime.now(tz=timezone.utc)


def _min_fraction_of_last_run(session: Session) -> float:
    try:
        return float(get_setting(session, "hr_sync.min_fraction_of_last_run"))
    except SettingNotFound:
        return 0.5


def _notify_admins_of_anomaly(session: Session, run: HrPersonSync) -> None:
    admins = session.execute(select(Soldier).where(Soldier.role == "admin")).scalars().all()
    for admin in admins:
        create_notification(
            session, soldier_id=admin.id, type=NotificationType.hr_sync_anomaly_aborted,
            title="HR sync aborted: unexpectedly few users returned",
            body=run.error_message,
        )


async def run_person_sync(session: Session, client: HrApiClient) -> HrPersonSync:
    run = HrPersonSync()
    session.add(run)
    session.commit()
    session.refresh(run)

    users = [user async for user in client.iter_users()]
    run.total_fetched = len(users)

    last_completed = session.execute(
        select(HrPersonSync)
        .where(HrPersonSync.status == "completed", HrPersonSync.id != run.id)
        .order_by(HrPersonSync.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if last_completed is not None and last_completed.total_fetched > 0:
        fraction = len(users) / last_completed.total_fetched
        if fraction < _min_fraction_of_last_run(session):
            run.status = "aborted_anomaly"
            run.error_message = (
                f"fetched {len(users)} users, below {_min_fraction_of_last_run(session):.0%} "
                f"of last run's {last_completed.total_fetched}"
            )
            run.completed_at = datetime.now(tz=timezone.utc)
            _notify_admins_of_anomaly(session, run)
            session.commit()
            return run

    seen_personal_numbers: set[str] = set()
    created = updated = held = error_count = 0

    for user in users:
        seen_personal_numbers.add(user.personal_number)
        try:
            mapped = map_hr_user(user)
            if isinstance(mapped, HeldForReview):
                _mark_held(session, user, mapped)
                held += 1
            else:
                profile = session.execute(
                    select(SoldierHrProfile).where(SoldierHrProfile.personal_number == mapped.personal_number)
                ).scalar_one_or_none()
                if profile is not None and profile.soldier_id is not None:
                    _apply_existing_person(session, profile, user, mapped)
                    updated += 1
                else:
                    _apply_new_person(session, user, mapped)
                    created += 1
            session.commit()
        except Exception as exc:
            session.rollback()
            session.add(HrPersonSyncError(
                hr_person_sync_id=run.id, personal_number=user.personal_number, error_message=str(exc),
            ))
            session.commit()
            error_count += 1

    vanished = 0
    linked_profiles = session.execute(
        select(SoldierHrProfile).where(
            SoldierHrProfile.soldier_id.is_not(None), SoldierHrProfile.sync_status == "synced",
        )
    ).scalars().all()
    for profile in linked_profiles:
        if profile.personal_number not in seen_personal_numbers:
            profile.sync_status = "vanished"
            vanished += 1
    session.commit()

    run.created_count = created
    run.updated_count = updated
    run.held_count = held
    run.vanished_count = vanished
    run.error_count = error_count
    run.status = "completed"
    run.completed_at = datetime.now(tz=timezone.utc)
    session.commit()
    return run
