from __future__ import annotations

import uuid
from datetime import date

from app.db.models import ExemptionType, Soldier
from app.services.exemption_requests import (
    ExemptionRequestError, approve_commander_step, approve_duty_manager_step,
    reject_request, submit_commander_escalation, submit_request,
)


def _soldier(session, **kw):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", **kw)
    session.add(s)
    session.flush()
    return s


def test_submit_request_starts_at_pending_commander(app_session):
    et = ExemptionType(name="פטור רפואי")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    assert req.status == "pending_commander"


def test_approve_commander_step_moves_to_pending_duty_manager(app_session):
    et = ExemptionType(name="פטור רפואי 2")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    approver = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    result = approve_commander_step(app_session, req.id, approved_by=approver.id)
    assert result.status == "pending_duty_manager"
    assert result.commander_approved_by == approver.id


def test_approve_duty_manager_step_finalizes_and_creates_exemption(app_session):
    et = ExemptionType(name="פטור רפואי 3")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    result = approve_duty_manager_step(app_session, req.id, decided_by=dm.id)
    assert result.status == "approved"
    assert result.decided_by == dm.id

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    ex = app_session.execute(select(SoldierExemption).where(SoldierExemption.soldier_id == soldier.id)).scalar_one()
    assert ex.granted_by == dm.id


def test_cannot_skip_commander_step(app_session):
    et = ExemptionType(name="פטור רפואי 4")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    try:
        approve_duty_manager_step(app_session, req.id, decided_by=dm.id)
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "not_pending_duty_manager" in str(exc)


def test_reject_works_at_commander_stage(app_session):
    et = ExemptionType(name="פטור רפואי 5")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    result = reject_request(app_session, req.id, decided_by=commander.id)
    assert result.status == "rejected"


def test_submit_request_rejects_commander_exemption_type(app_session):
    et = ExemptionType(name="פטור פיקודי", is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    try:
        submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "commander_exemption_not_requestable" in str(exc)


def test_reject_works_at_duty_manager_stage(app_session):
    et = ExemptionType(name="פטור רפואי 6")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    result = reject_request(app_session, req.id, decided_by=dm.id)
    assert result.status == "rejected"


def test_escalation_apply_immediately_grants_and_creates_pending_dm_request(app_session):
    official = ExemptionType(name="פטור רפואי אסקלציה 1")
    commander_type = ExemptionType(name="פטור פיקודי אסקלציה 1", is_commander_exemption=True)
    app_session.add_all([official, commander_type])
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    req = submit_commander_escalation(
        app_session,
        soldier_id=soldier.id,
        official_exemption_type_id=official.id,
        commander_exemption_type_id=commander_type.id,
        start_date=date(2026, 1, 1),
        end_date=None,
        reason="סיבה",
        apply_immediately=True,
        actor_id=commander.id,
    )

    assert req.status == "pending_duty_manager"
    assert req.commander_approved_by == commander.id
    assert req.exemption_type_id == official.id
    assert req.linked_commander_exemption_id is not None

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    ex = app_session.execute(
        select(SoldierExemption).where(SoldierExemption.id == req.linked_commander_exemption_id)
    ).scalar_one()
    assert ex.soldier_id == soldier.id
    assert ex.exemption_type_id == commander_type.id
    assert ex.granted_by == commander.id


def test_escalation_request_only_does_not_grant_exemption(app_session):
    official = ExemptionType(name="פטור רפואי אסקלציה 2")
    app_session.add(official)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    req = submit_commander_escalation(
        app_session,
        soldier_id=soldier.id,
        official_exemption_type_id=official.id,
        commander_exemption_type_id=None,
        start_date=date(2026, 1, 1),
        end_date=None,
        reason="סיבה",
        apply_immediately=False,
        actor_id=commander.id,
    )

    assert req.status == "pending_duty_manager"
    assert req.linked_commander_exemption_id is None

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    count = len(
        app_session.execute(
            select(SoldierExemption).where(SoldierExemption.soldier_id == soldier.id)
        ).scalars().all()
    )
    assert count == 0


def test_escalation_rejects_commander_type_as_official_target(app_session):
    commander_type = ExemptionType(name="פטור פיקודי אסקלציה 3", is_commander_exemption=True)
    app_session.add(commander_type)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    try:
        submit_commander_escalation(
            app_session,
            soldier_id=soldier.id,
            official_exemption_type_id=commander_type.id,
            commander_exemption_type_id=None,
            start_date=date(2026, 1, 1),
            end_date=None,
            reason="סיבה",
            apply_immediately=False,
            actor_id=commander.id,
        )
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "official_exemption_type_required" in str(exc)


def test_escalation_apply_immediately_requires_commander_type(app_session):
    official = ExemptionType(name="פטור רפואי אסקלציה 4")
    app_session.add(official)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    try:
        submit_commander_escalation(
            app_session,
            soldier_id=soldier.id,
            official_exemption_type_id=official.id,
            commander_exemption_type_id=None,
            start_date=date(2026, 1, 1),
            end_date=None,
            reason="סיבה",
            apply_immediately=True,
            actor_id=commander.id,
        )
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "commander_exemption_type_required" in str(exc)
