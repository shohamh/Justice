from __future__ import annotations

import logging
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
    HrRankConflict,
    NotificationType,
    Soldier,
    SoldierHrProfile,
)
from app.services.duty_eligibility_watch import recheck_soldier_assignments
from app.services.hr.client import HrApiClient
from app.services.hr.conflicts import (
    DuplicatePlan,
    build_candidate,
    ensure_email_applicable,
    ensure_no_unresolved_duplicate,
    group_feed_by_personal_number,
    latest_plan,
    normalize_personal_number,
    plan_duplicate,
    record_hr_conflict,
    soldiers_with_personal_number,
)
from app.services.hr.divergence import record_sync_divergence
from app.services.hr.errors import HrIdentityConflictError
from app.services.hr.mapping import HR_OWNED_FIELDS, HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.schemas import HrUser
from app.services.identity_write import assign_soldier_email
from app.services.notifications import create_notification, notify_commanders_of_request
from app.services.rank_advancement import get_next_rank, resolve_track
from app.services.settings_loader import SettingNotFound, get_setting
from app.services.soldiers import _reset_rank_advancement

logger = logging.getLogger(__name__)


def _assign_hr_email(session: Session, soldier: Soldier, raw_email: str | None) -> None:
    """Apply HR's email through the shared identity invariant.

    An unsupported address, or one that collides with another soldier's email
    or AD username, is not applied: the soldier's existing email stays as it
    was and the rest of the person still syncs. Logs the soldier id and the
    reason code only (no address). The sync loop checks the email first
    (``ensure_email_applicable``) and records an admin-visible conflict; this
    is the safety net for a race between that check and the write.
    """
    try:
        assign_soldier_email(session, soldier, raw_email)
    except ValueError as exc:
        logger.warning("HR sync: email not applied for soldier %s (%s)", soldier.id, exc)


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


def _multiple_local_records(personal_number: str, user: HrUser | None = None) -> HrIdentityConflictError:
    """Several local rows share one personal number (the DB forbids it; checked anyway)."""
    return HrIdentityConflictError(
        personal_number=normalize_personal_number(personal_number),
        kind="duplicate_personal_number", reason="multiple_local_records",
        candidates=[build_candidate(0, user)] if user is not None else [], applied_index=None,
    )


def _find_or_create_soldier_hr_profile(session: Session, personal_number: str) -> SoldierHrProfile:
    profiles = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.personal_number == personal_number)
    ).scalars().all()
    if len(profiles) > 1:
        raise _multiple_local_records(personal_number)
    profile = profiles[0] if profiles else None
    if profile is None:
        profile = SoldierHrProfile(personal_number=personal_number, raw_dto={})
        session.add(profile)
        session.flush()
    return profile


def _apply_new_person(
    session: Session, user: HrUser, mapped: MappedSoldierFields, *, hr_person_sync_id: uuid.UUID | None = None,
    apply_email: bool = True,
) -> tuple[Soldier, SoldierHrProfile]:
    soldiers = soldiers_with_personal_number(session, mapped.personal_number)
    if len(soldiers) > 1:
        raise _multiple_local_records(mapped.personal_number, user)
    soldier = soldiers[0] if soldiers else None

    if soldier is None:
        node_id = resolve_placement_node_id(session, user)
        soldier = Soldier(
            personal_number=mapped.personal_number,
            full_name=mapped.full_name,
            password_hash=hash_password(secrets.token_hex(16)),
            must_change_password=True,
            hierarchy_node_id=node_id,
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
        if apply_email:
            _assign_hr_email(session, soldier, mapped.email)
        session.add(soldier)
        session.flush()

        profile = _find_or_create_soldier_hr_profile(session, mapped.personal_number)
        profile.soldier_id = soldier.id
        profile.raw_dto = user.model_dump(by_alias=True)
        profile.sync_status = "synced"
        profile.review_reason = None
        profile.review_dismissed_at = None
        profile.review_dismissed_reasons = None
        profile.last_synced_at = datetime.now(tz=timezone.utc)
        return soldier, profile

    # An already-existing Soldier row (e.g. manually enrolled before HR sync
    # existed) matches this HR person by personal_number. Link the profile to
    # it, then apply the mapped HR fields through the normal override-aware
    # update path (_apply_existing_person) so the soldier's actual field
    # values don't sit stale for a whole extra sync run — it never touches
    # password_hash / role / hierarchy_node_id, so this is safe even though
    # the soldier predates HR sync.
    profile = _find_or_create_soldier_hr_profile(session, mapped.personal_number)
    profile.soldier_id = soldier.id
    profile.review_reason = None
    _apply_existing_person(
        session, profile, user, mapped, hr_person_sync_id=hr_person_sync_id, is_first_link=True,
        apply_email=apply_email,
    )
    return soldier, profile


def _mark_held(session: Session, user: HrUser, held: HeldForReview) -> SoldierHrProfile:
    profile = _find_or_create_soldier_hr_profile(session, held.personal_number)
    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "held_for_review"
    profile.review_reason = "; ".join(held.reasons)
    profile.last_synced_at = datetime.now(tz=timezone.utc)
    if profile.review_dismissed_reasons != held.reasons:
        profile.review_dismissed_at = None
        profile.review_dismissed_reasons = None
    return profile


_DEPENDENT_LOGIC_TRIGGER_FIELDS = frozenset({"rank", "mandatory_end_date", "discharge_date"})


def _flag_rank_conflict_if_needed(
    session: Session, *, soldier: Soldier, old_rank: str, new_rank: str,
    hr_person_sync_id: uuid.UUID | None = None, is_first_link: bool = False,
) -> None:
    """Record a conflict and notify the soldier + their commander(s) when
    HR's incoming rank either overrides a decision the worker made on its
    own, or isn't a simple one-step advance from where the soldier was.
    HR's value is applied regardless (HR stays authoritative) -- this is a
    visibility/audit action, not a block.

    Both `create_notification` (soldier) and `notify_commanders_of_request`
    (commanders) are called: `hr_rank_conflict` is deliberately excluded from
    `create_notification`'s automatic commander cascade (see
    notifications.py) precisely so the soldier's own notification preference
    can never silently suppress their commander's copy too -- the explicit
    call here is unconditional on that.

    `is_first_link=True` (the very first time an HR profile is linked to a
    soldier, e.g. one manually enrolled before HR sync existed) still records
    the HrRankConflict row for admin visibility, but skips both
    notifications: two independently-maintained systems reconciling for the
    first time will routinely disagree by more than one step, and flooding
    every newly-linked soldier and their commander on initial rollout isn't
    a meaningful signal the way an in-flight conflict is.
    """
    triggered_by_worker_decision = soldier.rank_last_set_by == "worker"
    track = resolve_track(old_rank, soldier.rank_track)
    expected_next = get_next_rank(old_rank, track=track) if old_rank else None
    non_sequential_jump = new_rank != expected_next

    if not (triggered_by_worker_decision or non_sequential_jump):
        return

    session.add(HrRankConflict(
        soldier_id=soldier.id, old_rank=old_rank, new_rank=new_rank,
        triggered_by_worker_decision=triggered_by_worker_decision,
        non_sequential_jump=non_sequential_jump,
        hr_person_sync_id=hr_person_sync_id,
    ))
    if is_first_link:
        return
    title = "דרגתך עודכנה בעקבות סנכרון מול מערכת משאבי אנוש"
    body = f"הדרגה עודכנה מ-{old_rank} ל-{new_rank} בעקבות נתוני משאבי אנוש, שאינם תואמים את ההתקדמות הצפויה."
    create_notification(
        session, soldier_id=soldier.id, type=NotificationType.hr_rank_conflict,
        title=title, body=body, reference_type="soldier", reference_id=soldier.id,
    )
    notify_commanders_of_request(
        session, soldier_id=soldier.id, type=NotificationType.hr_rank_conflict,
        title=title, body=body, reference_type="soldier", reference_id=soldier.id,
    )


def _apply_existing_person(
    session: Session, profile: SoldierHrProfile, user: HrUser, mapped: MappedSoldierFields,
    *, hr_person_sync_id: uuid.UUID | None = None, is_first_link: bool = False,
    apply_email: bool = True,
) -> None:
    soldier = session.get(Soldier, profile.soldier_id)
    changed_dependent_field = False
    calendar_changed = any(
        field not in profile.overridden_fields and getattr(soldier, field) != getattr(mapped, field)
        for field in ("full_name", "email")
    )
    if calendar_changed:
        from app.services.exchange_calendar.triggers import enqueue_affected_by_soldier
        # Resolve contacts under the old name before applying HR-owned fields.
        enqueue_affected_by_soldier(session, soldier.id)

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
        if field_name == "email":
            if apply_email:
                _assign_hr_email(session, soldier, new_value)
            continue
        old_value = getattr(soldier, field_name)
        if field_name in _DEPENDENT_LOGIC_TRIGGER_FIELDS and old_value != new_value:
            changed_dependent_field = True
        if field_name == "rank" and old_value != new_value and old_value is not None:
            _flag_rank_conflict_if_needed(
                session, soldier=soldier, old_rank=old_value, new_rank=new_value,
                hr_person_sync_id=hr_person_sync_id, is_first_link=is_first_link,
            )
        setattr(soldier, field_name, new_value)
        if field_name == "rank" and old_value != new_value:
            soldier.rank_last_set_by = "hr_sync"

    soldier.is_officer = mapped.is_officer
    soldier.is_career = mapped.is_career

    if changed_dependent_field:
        _reset_rank_advancement(session, soldier, since=date.today())
        recheck_soldier_assignments(session, soldier.id)

    if calendar_changed:
        session.flush()
        enqueue_affected_by_soldier(session, soldier.id)

    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "synced"
    profile.review_dismissed_at = None
    profile.review_dismissed_reasons = None
    profile.last_synced_at = datetime.now(tz=timezone.utc)


def apply_hr_record(
    session: Session, user: HrUser, mapped: MappedSoldierFields, *,
    hr_person_sync_id: uuid.UUID | None = None, apply_email: bool = True,
) -> str:
    """Apply one mapped HR record through the normal write path.

    Returns ``"updated"`` (an existing soldier was updated or linked) or
    ``"created"``. Used by the sync loop and by the admin "choose record"
    action, so a chosen record is written exactly as a sync would write it.
    """
    profiles = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.personal_number == mapped.personal_number)
    ).scalars().all()
    if len(profiles) > 1:
        raise _multiple_local_records(mapped.personal_number, user)
    profile = profiles[0] if profiles else None
    if profile is not None and profile.soldier_id is not None:
        _apply_existing_person(
            session, profile, user, mapped, hr_person_sync_id=hr_person_sync_id, apply_email=apply_email,
        )
        return "updated"
    # Distinguish "brand-new Soldier row created" from "linked to an
    # already-existing Soldier" (e.g. one manually enrolled before HR sync
    # existed) so the latter isn't miscounted as "created".
    pre_existing = soldiers_with_personal_number(session, mapped.personal_number)
    _apply_new_person(
        session, user, mapped, hr_person_sync_id=hr_person_sync_id, apply_email=apply_email,
    )
    return "updated" if pre_existing else "created"


def _detect(check, *args, **kwargs) -> HrIdentityConflictError | None:
    """Run an identity check; return the conflict it raises (None if it passes)."""
    try:
        check(*args, **kwargs)
    except HrIdentityConflictError as exc:
        return exc
    return None


def _plan_duplicates(session: Session, users: list[HrUser]) -> dict[str, DuplicatePlan]:
    """Decide, before the loop, which record to apply for each duplicated personal number."""
    plans: dict[str, DuplicatePlan] = {}
    for personal_number, positions in group_feed_by_personal_number(users).items():
        if len(positions) < 2:
            continue
        try:
            plans[personal_number] = plan_duplicate(session, personal_number, positions, users)
        except Exception:
            logger.exception("HR sync: could not evaluate remembered choice for %s", personal_number)
            session.rollback()
            plans[personal_number] = latest_plan(personal_number, positions, users, reason="latest")
    return plans


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
            title="סנכרון משא\"ן הופסק: התקבלו פחות משתמשים מהצפוי",
            body=run.error_message,
        )


async def run_person_sync(session: Session, client: HrApiClient) -> HrPersonSync:
    run = HrPersonSync()
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        users = [user async for user in client.iter_users()]
        run.total_fetched = len(users)
        # Committed separately (not deferred to the per-person loop's own
        # commits) so an early per-person failure's rollback can't discard
        # it — the NEXT run's anomaly baseline depends on this surviving.
        session.commit()

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
        created = updated = held = error_count = conflict_count = 0
        duplicate_plans = _plan_duplicates(session, users)

        for position, user in enumerate(users):
            seen_personal_numbers.add(user.personal_number)
            plan = duplicate_plans.get(normalize_personal_number(user.personal_number))
            if plan is not None and position != plan.applied_position:
                # An earlier or non-chosen occurrence of a duplicated personal
                # number: only the applied record is written (see conflicts.py).
                continue
            try:
                detected: list[HrIdentityConflictError] = []
                duplicate_error = _detect(ensure_no_unresolved_duplicate, plan)
                if duplicate_error is not None:
                    detected.append(duplicate_error)
                mapped = map_hr_user(user)
                if isinstance(mapped, HeldForReview):
                    _mark_held(session, user, mapped)
                    held += 1
                else:
                    soldiers = soldiers_with_personal_number(session, mapped.personal_number)
                    if len(soldiers) > 1:
                        raise _multiple_local_records(mapped.personal_number, user)
                    email_overridden = False
                    if soldiers:
                        profile = session.execute(
                            select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == soldiers[0].id)
                        ).scalar_one_or_none()
                        email_overridden = profile is not None and "email" in profile.overridden_fields
                    apply_email = True
                    if not email_overridden:
                        email_error = _detect(
                            ensure_email_applicable, session, user,
                            own_soldier_ids=[s.id for s in soldiers],
                        )
                        if email_error is not None:
                            detected.append(email_error)
                            apply_email = False
                    outcome = apply_hr_record(
                        session, user, mapped, hr_person_sync_id=run.id, apply_email=apply_email,
                    )
                    if outcome == "created":
                        created += 1
                    else:
                        updated += 1
                recorded = sum(
                    record_hr_conflict(session, error, hr_person_sync_id=run.id) for error in detected
                )
                session.commit()
                conflict_count += recorded
            except HrIdentityConflictError as exc:
                # Structural conflict with nothing applied (several local rows
                # for one personal number): warn, skip the person, keep going.
                session.rollback()
                if record_hr_conflict(session, exc, hr_person_sync_id=run.id):
                    conflict_count += 1
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
        run.conflict_count = conflict_count
        run.status = "completed"
        run.completed_at = datetime.now(tz=timezone.utc)
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(tz=timezone.utc)
        session.commit()

    return run
