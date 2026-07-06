from __future__ import annotations

import uuid

from sqlalchemy import select

from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_notify_duty_managers_in_scope_reaches_dm_with_scope(admin_session):
    from app.db.models import DutyManagerScope, Notification, NotificationType
    from app.services.notifications import notify_duty_managers_in_scope

    node = create_node(admin_session, level="unit", name=f"dm_scope_test_node_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"dm_scope_1_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"dm_scope_dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    notify_duty_managers_in_scope(
        admin_session, soldier_id=soldier.id, type=NotificationType.exemption_revoked,
        title="test title", reference_type="soldier_exemption", reference_id=soldier.id,
        actor_id=None,
    )
    admin_session.commit()

    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == dm.id)
    ).scalar_one_or_none()
    assert notif is not None
    assert notif.title == f"{soldier.full_name}: test title"


def test_notify_duty_managers_in_scope_skips_dm_without_scope(admin_session):
    from app.db.models import Notification, NotificationType
    from app.services.notifications import notify_duty_managers_in_scope

    node = create_node(admin_session, level="unit", name=f"dm_no_scope_test_node_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"dm_no_scope_1_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"dm_no_scope_dm_{_uid()}", role="duty_manager")
    admin_session.commit()

    notify_duty_managers_in_scope(
        admin_session, soldier_id=soldier.id, type=NotificationType.exemption_revoked,
        title="test title", actor_id=None,
    )
    admin_session.commit()

    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == dm.id)
    ).scalar_one_or_none()
    assert notif is None
