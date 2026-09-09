from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyType, Notification, NotificationType, RangeType
from app.services.duty_config import create_duty_type, update_duty_type
from tests.helpers import create_node, create_soldier


def test_create_duty_type_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_dt1")
    dt = create_duty_type(
        admin_session,
        name="dt_with_scope",
        score_per_day=Decimal("1.00"),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert dt.eligible_node_ids == [node.id]


def test_create_duty_type_without_eligible_node_ids_defaults_to_none(admin_session):
    dt = create_duty_type(admin_session, name="dt_unscoped", score_per_day=Decimal("1.00"))
    admin_session.commit()
    assert dt.eligible_node_ids is None


def test_update_duty_type_sets_and_clears_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_dt2")
    dt = create_duty_type(admin_session, name="dt_update_scope", score_per_day=Decimal("1.00"))
    admin_session.commit()

    update_duty_type(
        admin_session, duty_type=dt, name=None, score_per_day=None, description=None,
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert dt.eligible_node_ids == [node.id]

    update_duty_type(
        admin_session, duty_type=dt, name=None, score_per_day=None, description=None,
        eligible_node_ids=None,
    )
    admin_session.commit()
    assert dt.eligible_node_ids is None


def test_create_duty_type_accepts_required_range_type(app_session) -> None:
    dt = create_duty_type(
        app_session, name="dc-weapon-1", score_per_day=Decimal("1.00"), description=None,
        is_external=False, requires_weapon=True, required_range_type=RangeType.live,
    )
    app_session.commit()
    app_session.refresh(dt)
    assert dt.required_range_type == "live"


def test_update_duty_type_sets_required_range_type(app_session) -> None:
    dt = DutyType(name="dc-weapon-2", score_per_day=Decimal("1.00"), requires_weapon=True)
    app_session.add(dt)
    app_session.commit()

    updated = update_duty_type(
        app_session, duty_type=dt, name=None, score_per_day=None, description=None,
        required_range_type=RangeType.alal,
    )
    app_session.commit()
    app_session.refresh(updated)
    assert updated.required_range_type == "alal"

def test_update_duty_type_clears_required_range_type_when_explicitly_none(app_session) -> None:
    dt = DutyType(
        name="dc-weapon-clear", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    app_session.add(dt)
    app_session.commit()

    updated = update_duty_type(
        app_session, duty_type=dt, name=None, score_per_day=None, description=None,
        required_range_type=None,
    )
    app_session.commit()
    app_session.refresh(updated)
    assert updated.required_range_type is None


def test_update_duty_type_leaves_required_range_type_untouched_when_omitted(app_session) -> None:
    dt = DutyType(
        name="dc-weapon-3", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    app_session.add(dt)
    app_session.commit()

    update_duty_type(app_session, duty_type=dt, name="dc-weapon-3-renamed", score_per_day=None, description=None)
    app_session.commit()
    app_session.refresh(dt)
    assert dt.required_range_type == "laser"


def test_update_duty_type_notifies_on_duty_soldiers_and_their_commanders_on_instructions_change(
    admin_session,
) -> None:
    root = create_node(admin_session, level="division", name="div_notif1")
    commander = create_soldier(admin_session, personal_number="dutynotif001", hierarchy_node_id=root.id)
    root.commander_id = commander.id
    admin_session.flush()
    on_duty_soldier = create_soldier(
        admin_session, personal_number="dutynotif002", hierarchy_node_id=root.id
    )
    duty_type = create_duty_type(admin_session, name="שמירה-notif", score_per_day=Decimal("1.00"))
    location = DutyLocation(name="מיקום notif")
    admin_session.add(location)
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=on_duty_soldier.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=date.today(), end_date=date.today() + timedelta(days=1), status="published",
    ))
    admin_session.commit()

    update_duty_type(
        admin_session, duty_type=duty_type, name=None, score_per_day=None, description=None,
        instructions="הנחיות חדשות",
    )
    admin_session.commit()

    notifs = admin_session.query(Notification).filter_by(soldier_id=on_duty_soldier.id).all()
    assert any(n.type == NotificationType.duty_instructions_updated for n in notifs)
    commander_notifs = admin_session.query(Notification).filter_by(soldier_id=commander.id).all()
    assert any(n.type == NotificationType.duty_instructions_updated for n in commander_notifs)


def test_update_duty_type_does_not_notify_on_unrelated_field_change(admin_session) -> None:
    root = create_node(admin_session, level="division", name="div_notif2")
    commander = create_soldier(admin_session, personal_number="dutynotif003", hierarchy_node_id=root.id)
    root.commander_id = commander.id
    admin_session.flush()
    on_duty_soldier = create_soldier(
        admin_session, personal_number="dutynotif004", hierarchy_node_id=root.id
    )
    duty_type = create_duty_type(admin_session, name="שמירה-notif2", score_per_day=Decimal("1.00"))
    location = DutyLocation(name="מיקום notif2")
    admin_session.add(location)
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=on_duty_soldier.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=date.today(), end_date=date.today() + timedelta(days=1), status="published",
    ))
    admin_session.commit()

    update_duty_type(
        admin_session, duty_type=duty_type, name=None, score_per_day=Decimal("2.00"), description=None,
    )
    admin_session.commit()

    notifs = admin_session.query(Notification).filter_by(soldier_id=on_duty_soldier.id).all()
    assert not any(n.type == NotificationType.duty_instructions_updated for n in notifs)
    commander_notifs = admin_session.query(Notification).filter_by(soldier_id=commander.id).all()
    assert not any(n.type == NotificationType.duty_instructions_updated for n in commander_notifs)
