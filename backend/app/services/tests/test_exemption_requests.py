from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from sqlalchemy import delete, select

from app.db.models import (
    CommanderNotificationScope,
    DutyManagerScope,
    ExemptionType,
    HierarchyLevelType,
    HierarchyNode,
    Notification,
    NotificationType,
    Soldier,
)
from app.services.exemption_requests import (
    ExemptionRequestError, approve_commander_step, approve_duty_manager_step,
    reject_request, submit_commander_escalation, submit_request,
)
from app.services.authority import REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY


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
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
    assert req.status == "pending_commander"


def test_approve_commander_step_moves_to_pending_duty_manager(app_session):
    et = ExemptionType(name="פטור רפואי 2")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    approver = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
    result = approve_commander_step(app_session, req.id, approved_by=approver.id)
    assert result.status == "pending_duty_manager"
    assert result.commander_approved_by == approver.id


def test_approve_commander_step_notifies_duty_managers(app_session):
    """When a commander approves their step, duty managers in scope over the
    soldier's node must get a pending-approval notification — mirroring what
    submit_commander_escalation already does when landing directly in
    pending_duty_manager (see test_notifications_dm.py for the DM-scope
    fixture pattern reused here)."""
    # The shared English-keyed level defaults (seeded by conftest's
    # _truncate_tables fixture) don't include a level whose key matches
    # REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY ("מרכז"), so dm_scope_covers_level
    # would never find a rank and no DM would ever qualify. Replace them
    # with a minimal Hebrew-keyed hierarchy, as test_notifications_dm.py does.
    app_session.execute(delete(HierarchyLevelType))
    app_session.add(HierarchyLevelType(key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
                                        label=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, rank=1))
    app_session.add(HierarchyLevelType(key="פלוגה", label="פלוגה", rank=2))
    app_session.flush()

    center_node = HierarchyNode(level=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, name="Center", path_ids=[])
    app_session.add(center_node)
    app_session.flush()
    center_node.path_ids = [center_node.id]

    co_node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(co_node)
    app_session.flush()
    co_node.path_ids = [center_node.id, co_node.id]
    app_session.flush()

    et = ExemptionType(name="פטור רפואי - dm notify")
    app_session.add(et)
    app_session.flush()

    soldier = _soldier(app_session, hierarchy_node_id=co_node.id)
    commander = _soldier(app_session)
    dm = _soldier(app_session)
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=center_node.id))
    app_session.flush()

    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
    approve_commander_step(app_session, req.id, approved_by=commander.id)

    notif = app_session.query(Notification).filter_by(
        soldier_id=dm.id, type=NotificationType.exemption_request_pending,
    ).one_or_none()
    assert notif is not None


def test_submit_request_tags_target_tab_by_recipient_authority(app_session):
    """The commander-notification cascade (CommanderNotificationScope) notifies
    every commander who opted into visibility over the soldier's subtree —
    wider than who can actually decide the commander step. A notified admin
    can always decide (exemption_approval_flags short-circuits on role ==
    "admin"), so their notification should point at the "exemptions" tab; a
    plain soldier with no command/DM authority cannot, so theirs should point
    at "waiting" instead — see _exemption_actionable_check."""
    node = HierarchyNode(level="unit", name="target-tab-node", path_ids=[])
    app_session.add(node)
    app_session.flush()
    node.path_ids = [node.id]
    app_session.flush()

    et = ExemptionType(name="פטור רפואי - target tab")
    app_session.add(et)
    app_session.flush()

    soldier = _soldier(app_session, hierarchy_node_id=node.id)
    actionable_recipient = _soldier(app_session, role="admin")
    non_actionable_recipient = _soldier(app_session)
    app_session.add(CommanderNotificationScope(commander_id=actionable_recipient.id, hierarchy_node_id=node.id))
    app_session.add(CommanderNotificationScope(commander_id=non_actionable_recipient.id, hierarchy_node_id=node.id))
    app_session.flush()

    submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")

    actionable_notif = app_session.query(Notification).filter_by(
        soldier_id=actionable_recipient.id, type=NotificationType.exemption_request_pending,
    ).one()
    assert actionable_notif.metadata_json == {"target_tab": "exemptions"}

    waiting_notif = app_session.query(Notification).filter_by(
        soldier_id=non_actionable_recipient.id, type=NotificationType.exemption_request_pending,
    ).one()
    assert waiting_notif.metadata_json == {"target_tab": "waiting"}


def test_approve_duty_manager_step_finalizes_and_creates_exemption(app_session):
    et = ExemptionType(name="פטור רפואי 3")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
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
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
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
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
    result = reject_request(app_session, req.id, decided_by=commander.id)
    assert result.status == "rejected"


def test_submit_request_rejects_commander_exemption_type(app_session):
    et = ExemptionType(name="פטור פיקודי", is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    try:
        submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
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
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1), reason="סיבה")
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    result = reject_request(app_session, req.id, decided_by=dm.id)
    assert result.status == "rejected"


def test_reject_request_notification_includes_type_name_and_dates(app_session):
    et = ExemptionType(name="חופשה")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    decider = _soldier(app_session)
    req = submit_request(
        app_session, soldier.id, et.id,
        start_date=date(2026, 8, 10), end_date=date(2026, 8, 15), reason="סיבה",
    )
    reject_request(app_session, request_id=req.id, decided_by=decider.id,
                   decision_note="לא מספיק ימי חופשה")
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.reference_id == req.id,
            Notification.type == NotificationType.exemption_rejected,
        )
    ).scalar_one()
    assert "חופשה" in notif.title
    assert "2026-08-10" in notif.title and "2026-08-15" in notif.title
    assert notif.body == "לא מספיק ימי חופשה"


def test_reject_request_notification_marks_permanent_exemption(app_session):
    et = ExemptionType(name="רפואי")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    decider = _soldier(app_session)
    req = submit_request(
        app_session, soldier.id, et.id,
        start_date=date(2026, 8, 10), end_date=None, reason="סיבה",
    )
    reject_request(app_session, request_id=req.id, decided_by=decider.id)
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.reference_id == req.id,
            Notification.type == NotificationType.exemption_rejected,
        )
    ).scalar_one()
    assert "קבוע" in notif.title


def test_approve_duty_manager_step_notification_includes_type_name_and_dates(app_session):
    et = ExemptionType(name="אישי")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    decider = _soldier(app_session)
    req = submit_request(
        app_session, soldier.id, et.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), reason="סיבה",
    )
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    approve_duty_manager_step(app_session, request_id=req.id, decided_by=decider.id)
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.reference_id == req.id,
            Notification.type == NotificationType.exemption_approved,
        )
    ).scalar_one()
    assert "אישי" in notif.title
    assert "2026-09-01" in notif.title and "2026-09-03" in notif.title


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


def test_submit_request_rejects_span_over_364_days(admin_session):
    from app.services.exemption_requests import submit_request, ExemptionRequestError
    from app.db.models import ExemptionType
    from tests.helpers import create_soldier

    et = ExemptionType(name="span_test_type", description=None)
    admin_session.add(et)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="7910001")

    start = date.today()
    with pytest.raises(ExemptionRequestError, match="date_range_too_long"):
        submit_request(
            admin_session, soldier.id, et.id,
            start_date=start, end_date=start + timedelta(days=365),
            reason="סיבה",
        )


def test_submit_request_allows_span_of_exactly_364_days(admin_session):
    from app.services.exemption_requests import submit_request
    from app.db.models import ExemptionType
    from tests.helpers import create_soldier

    et = ExemptionType(name="span_test_type_ok", description=None)
    admin_session.add(et)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="7910002")

    start = date.today()
    req = submit_request(
        admin_session, soldier.id, et.id,
        start_date=start, end_date=start + timedelta(days=364),
        reason="סיבה",
    )
    assert req.id is not None


def test_submit_request_allows_open_ended(admin_session):
    from app.services.exemption_requests import submit_request
    from app.db.models import ExemptionType
    from tests.helpers import create_soldier

    et = ExemptionType(name="span_test_type_open", description=None)
    admin_session.add(et)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="7910003")

    req = submit_request(admin_session, soldier.id, et.id, start_date=date.today(), end_date=None, reason="סיבה")
    assert req.end_date is None
