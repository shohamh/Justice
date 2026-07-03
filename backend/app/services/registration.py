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
from app.services.invite_codes import InviteCodeError, consume_invite_code
from app.services.settings_loader import SettingNotFound, get_setting


class RegistrationError(Exception):
    pass


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
    is_career: bool = False,
    rank: str | None,
    bahad1_graduate: bool,
    enlistment_date: date | None,
    mandatory_end_date: date | None,
    discharge_date: date | None,
    last_mitvahim_date: date | None,
    last_alal_date: date | None,
    requested_node_id: uuid.UUID,
    exemption_requests: list[dict],
    personal_constraints: list[dict],
) -> Soldier:
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
        is_career=is_career,
        rank=rank,
        bahad1_graduate=bahad1_graduate,
        enlistment_date=enlistment_date,
        mandatory_end_date=mandatory_end_date,
        discharge_date=discharge_date,
        last_mitvahim_date=last_mitvahim_date,
        last_alal_date=last_alal_date,
    )
    session.add(soldier)
    session.flush()

    enrollment_req = SoldierEnrollmentRequest(
        soldier_id=soldier.id,
        requested_node_id=requested_node_id,
        status="pending",
    )
    session.add(enrollment_req)
    session.flush()

    for er in exemption_requests:
        et = session.get(ExemptionType, er["exemption_type_id"])
        if et is None:
            raise RegistrationError("exemption_type_not_found")
        if et.is_commander_exemption:
            raise RegistrationError("commander_exemption_not_requestable")
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=er["exemption_type_id"],
            start_date=er["start_date"],
            end_date=er.get("end_date"),
            reason=er.get("reason"),
            status="pending_commander",
            enrollment_request_id=enrollment_req.id,
        ))

    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc["reason"],
            status="pending",
        ))

    session.flush()

    from app.services.notifications import notify_enrollment_received
    notify_enrollment_received(
        session,
        soldier=soldier,
        enrollment_req=enrollment_req,
        has_exemptions=len(exemption_requests) > 0,
    )

    return soldier
