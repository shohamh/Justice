from __future__ import annotations

import uuid

from sqlalchemy import select

from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_notifies_soldier_and_cascades_to_commander(app_session):
    from app.db.models import CommanderNotificationScope, Notification, NotificationType
    from app.services.notifications import notify_personal_constraint_overridden

    node = create_node(app_session, level="unit", name=f"pco_node_{_uid()}")
    commander = create_soldier(app_session, personal_number=f"pco_cmd_{_uid()}")
    soldier = create_soldier(app_session, personal_number=f"pco_sol_{_uid()}", hierarchy_node_id=node.id)
    app_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    app_session.commit()

    notify_personal_constraint_overridden(
        app_session,
        soldier_id=soldier.id,
        assignment_kind="duty",
        reason="צורך מבצעי דחוף",
        actor_id=commander.id,
    )
    app_session.flush()

    soldier_notifs = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.type == NotificationType.personal_constraint_overridden,
        )
    ).scalars().all()
    assert len(soldier_notifs) == 1
    assert "אילוץ אישי נדרס בשיבוץ לתורנות" in soldier_notifs[0].title
    assert soldier_notifs[0].body == "צורך מבצעי דחוף"

    commander_notifs = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == commander.id,
            Notification.type == NotificationType.personal_constraint_overridden,
        )
    ).scalars().all()
    assert len(commander_notifs) == 1


def test_range_wording(app_session):
    from app.db.models import Notification
    from app.services.notifications import notify_personal_constraint_overridden

    soldier = create_soldier(app_session, personal_number=f"pco_range_{_uid()}")
    notify_personal_constraint_overridden(
        app_session, soldier_id=soldier.id, assignment_kind="range", reason="r", actor_id=None,
    )
    app_session.flush()
    notif = app_session.execute(
        select(Notification).where(Notification.soldier_id == soldier.id)
    ).scalar_one()
    assert "אילוץ אישי נדרס בשיבוץ למטווח" in notif.title
