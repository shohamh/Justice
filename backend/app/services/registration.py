from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import (
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierEnrollmentRequest,
)
from app.services.eligibility import derive_bahad1_graduate, derive_is_career, validate_rank_track_compatibility
from app.services.invite_codes import InviteCodeError, consume_invite_code
from app.services.rank_advancement import compute_next_rank_date, resolve_track
from app.services.settings_loader import SettingNotFound, get_setting
from app.services.soldiers import PasswordPolicyError, SoldierError, _check_soldier_dates, validate_password


class RegistrationError(Exception):
    pass


def validate_full_name(full_name: str) -> None:
    if len(full_name) > 100:
        raise ValueError("full_name_too_long")
    if len(full_name.strip().split()) < 2:
        raise ValueError("full_name_requires_two_words")


def validate_personal_number(personal_number: str) -> None:
    if not personal_number.isascii() or not personal_number.isdigit() or not 7 <= len(personal_number) <= 8:
        raise ValueError("personal_number_invalid")


def validate_personal_constraint(constraint: dict) -> None:
    if not constraint.get("start_date") or not constraint.get("end_date") or not (constraint.get("reason") or "").strip():
        raise ValueError("constraint_missing_fields")


def register(
    session: Session,
    *,
    invite_code: str,
    personal_number: str,
    full_name: str,
    password: str,
    phone: str | None,
    email: str | None,
    gender: str | None,
    is_officer: bool | None,
    rank: str | None,
    enlistment_date: date | None,
    mandatory_end_date: date | None,
    discharge_date: date | None,
    last_mitvahim_date: date | None,
    last_alal_date: date | None,
    requested_node_id: uuid.UUID,
    exemption_requests: list[dict],
    personal_constraints: list[dict],
    has_military_driving_license: bool = False,
    military_driving_license_expiry: date | None = None,
    rank_track: str | None = None,
) -> tuple[Soldier, list[ExemptionRequest]]:
    try:
        validate_full_name(full_name)
    except ValueError as exc:
        raise RegistrationError(str(exc)) from exc

    try:
        validate_password(password)
    except PasswordPolicyError as exc:
        raise RegistrationError("password_policy") from exc

    consume_invite_code(session, code=invite_code)

    if session.execute(
        select(Soldier.id).where(Soldier.personal_number == personal_number)
    ).first():
        raise RegistrationError("personal_number already exists")

    try:
        holding_node_id = uuid.UUID(get_setting(session, "system.holding_node_id"))
    except SettingNotFound as exc:
        raise RegistrationError("holding node not bootstrapped") from exc

    if session.get(HierarchyNode, holding_node_id) is None:
        raise RegistrationError("holding node not bootstrapped")

    if session.get(HierarchyNode, requested_node_id) is None:
        raise RegistrationError("requested node not found")

    if discharge_date is not None and discharge_date < date.today():
        raise RegistrationError("discharge_date_in_past")

    is_career = derive_is_career(rank, mandatory_end_date, discharge_date)

    try:
        _check_soldier_dates(
            rank=rank, enlistment_date=enlistment_date, discharge_date=discharge_date,
            mandatory_end_date=mandatory_end_date, is_career=is_career,
        )
    except SoldierError as exc:
        raise RegistrationError(str(exc)) from exc

    try:
        validate_rank_track_compatibility(rank=rank, is_career=is_career)
    except ValueError as exc:
        raise RegistrationError(str(exc)) from exc

    bahad1_graduate = derive_bahad1_graduate(rank)
    resolved_rank_track = resolve_track(rank, rank_track)
    if rank is not None and rank_track is not None and resolved_rank_track != rank_track:
        raise RegistrationError("rank_track_invalid")

    soldier = Soldier(
        personal_number=personal_number,
        full_name=full_name,
        password_hash=hash_password(password),
        role="soldier",
        hierarchy_node_id=holding_node_id,
        phone=phone,
        email=email,
        must_change_password=False,
        gender=gender,
        is_officer=is_officer,
        rank=rank,
        rank_track=resolved_rank_track,
        is_career=is_career,
        bahad1_graduate=bahad1_graduate,
        enlistment_date=enlistment_date,
        mandatory_end_date=mandatory_end_date,
        discharge_date=discharge_date,
        last_mitvahim_date=last_mitvahim_date,
        last_alal_date=last_alal_date,
        has_military_driving_license=has_military_driving_license,
        military_driving_license_expiry=military_driving_license_expiry,
    )
    if rank is not None:
        soldier.current_rank_since = enlistment_date or date.today()
        soldier.next_rank_date = compute_next_rank_date(
            session, rank=rank, since=soldier.current_rank_since, track=resolved_rank_track
        )
        soldier.next_rank_date_overridden = False
    session.add(soldier)
    session.flush()

    enrollment_req = SoldierEnrollmentRequest(
        soldier_id=soldier.id,
        requested_node_id=requested_node_id,
        status="pending",
    )
    session.add(enrollment_req)
    session.flush()

    created_exemption_requests: list[ExemptionRequest] = []
    for er in exemption_requests:
        exemption_type_id_raw = er.get("exemption_type_id")
        start_date_raw = er.get("start_date")
        end_date_raw = er.get("end_date")
        if not exemption_type_id_raw:
            raise RegistrationError("exemption_missing_fields")
        if end_date_raw and not start_date_raw:
            raise RegistrationError("start_date_required")
        try:
            exemption_type_id = uuid.UUID(str(exemption_type_id_raw))
        except ValueError as exc:
            raise RegistrationError("exemption_missing_fields") from exc
        et = session.get(ExemptionType, exemption_type_id)
        if et is None:
            raise RegistrationError("exemption_type_not_found")
        if et.is_commander_exemption:
            raise RegistrationError("commander_exemption_not_requestable")
        if end_date_raw and start_date_raw and end_date_raw < start_date_raw:
            raise RegistrationError("bad_date_range")
        exemption_request = ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=exemption_type_id,
            start_date=start_date_raw or None,
            end_date=end_date_raw or None,
            reason=er.get("reason"),
            status="pending_commander",
            enrollment_request_id=enrollment_req.id,
        )
        session.add(exemption_request)
        created_exemption_requests.append(exemption_request)

    for pc in personal_constraints:
        try:
            validate_personal_constraint(pc)
        except ValueError as exc:
            raise RegistrationError(str(exc)) from exc
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc.get("reason"),
            status="pending_commander",
        ))

    session.flush()

    from app.services.notifications import notify_enrollment_received
    notify_enrollment_received(
        session,
        soldier=soldier,
        enrollment_req=enrollment_req,
        has_exemptions=len(exemption_requests) > 0,
    )

    return soldier, created_exemption_requests
