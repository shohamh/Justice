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


def test_bug_report_comment_notifications_open_the_referenced_bug_report():
    from app.db.models import NotificationType
    from app.services.notifications import _frontend_url

    report_id = uuid.UUID("00000000-0000-0000-0000-000000000123")
    assert _frontend_url(NotificationType.bug_report_comment, report_id).endswith(
        "/?bugReport=00000000-0000-0000-0000-000000000123"
    )


def test_bug_report_comment_notifications_open_the_bug_reports_page_without_reference():
    from app.db.models import NotificationType
    from app.services.notifications import _frontend_url

    assert _frontend_url(NotificationType.bug_report_comment).endswith("/")


def test_broadcast_announcement_restricted_to_hierarchy_only_reaches_descendants(admin_session):
    from app.db.models import Notification
    from app.services.notifications import broadcast_announcement

    root = create_node(admin_session, level="unit", name=f"bc_root_{_uid()}")
    selected = create_node(admin_session, level="unit", name=f"bc_selected_{_uid()}", parent=root)
    inside = create_node(admin_session, level="unit", name=f"bc_inside_{_uid()}", parent=selected)
    sibling = create_node(admin_session, level="unit", name=f"bc_sibling_{_uid()}", parent=root)

    in_scope_1 = create_soldier(admin_session, personal_number=f"bc1_{_uid()}", hierarchy_node_id=selected.id)
    in_scope_2 = create_soldier(admin_session, personal_number=f"bc2_{_uid()}", hierarchy_node_id=inside.id)
    out_of_scope = create_soldier(admin_session, personal_number=f"bc3_{_uid()}", hierarchy_node_id=sibling.id)
    actor = create_soldier(admin_session, personal_number=f"bc_actor_{_uid()}", role="admin")
    admin_session.commit()

    ann = broadcast_announcement(
        admin_session, title=f"test-{_uid()}", hierarchy_node_ids=[selected.id], actor_id=actor.id,
    )
    admin_session.commit()

    notified_ids = set(
        admin_session.execute(
            select(Notification.soldier_id).where(
                Notification.reference_type == "announcement",
                Notification.reference_id == ann.id,
            )
        ).scalars().all()
    )
    assert notified_ids == {in_scope_1.id, in_scope_2.id}
    assert out_of_scope.id not in notified_ids
    assert ann.recipient_count == 2


def test_create_notification_persists_metadata(app_session):
    from app.db.models import NotificationType
    from app.services.notifications import create_notification

    soldier = create_soldier(app_session, personal_number=f"meta_1_{_uid()}")
    notif = create_notification(
        app_session, soldier_id=soldier.id, type=NotificationType.announcement,
        title="test", metadata={"event_id": "abc-123"},
    )
    app_session.refresh(notif)
    assert notif.metadata_json == {"event_id": "abc-123"}


def test_create_notification_defaults_metadata_to_none(app_session):
    from app.db.models import NotificationType
    from app.services.notifications import create_notification

    soldier = create_soldier(app_session, personal_number=f"meta_2_{_uid()}")
    notif = create_notification(
        app_session, soldier_id=soldier.id, type=NotificationType.announcement, title="test",
    )
    assert notif.metadata_json is None


def test_notify_rank_advanced_creates_notification_for_soldier(app_session):
    from app.services.notifications import notify_rank_advanced
    from app.db.models import Notification, NotificationType

    s = create_soldier(app_session, personal_number=f"rank_adv_1_{_uid()}")
    notify_rank_advanced(app_session, soldier_id=s.id, new_rank="רבט")
    app_session.flush()
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == s.id, Notification.type == NotificationType.rank_advanced
        )
    ).scalar_one()
    assert "רבט" in notif.title


def test_notify_rank_advanced_creates_notification_for_commander(app_session):
    from app.services.notifications import notify_rank_advanced
    from app.db.models import Notification, NotificationType, CommanderNotificationScope

    node = create_node(app_session, level="unit", name=f"rank_adv_node_{_uid()}")
    commander = create_soldier(
        app_session, personal_number=f"rank_adv_cmd_{_uid()}", hierarchy_node_id=node.id
    )
    soldier = create_soldier(
        app_session, personal_number=f"rank_adv_sol_{_uid()}", hierarchy_node_id=node.id
    )
    app_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    app_session.commit()

    notify_rank_advanced(app_session, soldier_id=soldier.id, new_rank="רבט")
    app_session.flush()

    # Verify soldier received notification
    soldier_notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id, Notification.type == NotificationType.rank_advanced
        )
    ).scalar_one()
    assert "רבט" in soldier_notif.title

    # Verify commander received notification with soldier's name
    commander_notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == commander.id, Notification.type == NotificationType.rank_advanced
        )
    ).scalar_one()
    assert soldier.full_name in commander_notif.title
    assert "רבט" in commander_notif.title


def test_notify_rank_advancement_soon_creates_notification_for_soldier(app_session):
    from datetime import date
    from app.services.notifications import notify_rank_advancement_soon
    from app.db.models import Notification, NotificationType

    s = create_soldier(app_session, personal_number=f"rank_soon_1_{_uid()}")
    effective_date = date(2026, 8, 20)
    notify_rank_advancement_soon(app_session, soldier_id=s.id, new_rank="רבט", effective_date=effective_date)
    app_session.flush()
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == s.id, Notification.type == NotificationType.rank_advancement_soon
        )
    ).scalar_one()
    assert "רבט" in notif.title
    assert "20.08.2026" in notif.title


def test_notify_rank_advancement_soon_creates_notification_for_commander(app_session):
    from datetime import date
    from app.services.notifications import notify_rank_advancement_soon
    from app.db.models import Notification, NotificationType, CommanderNotificationScope

    node = create_node(app_session, level="unit", name=f"rank_soon_node_{_uid()}")
    commander = create_soldier(
        app_session, personal_number=f"rank_soon_cmd_{_uid()}", hierarchy_node_id=node.id
    )
    soldier = create_soldier(
        app_session, personal_number=f"rank_soon_sol_{_uid()}", hierarchy_node_id=node.id
    )
    app_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    app_session.commit()

    effective_date = date(2026, 8, 20)
    notify_rank_advancement_soon(app_session, soldier_id=soldier.id, new_rank="רבט", effective_date=effective_date)
    app_session.flush()

    # Verify soldier received notification
    soldier_notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id, Notification.type == NotificationType.rank_advancement_soon
        )
    ).scalar_one()
    assert "רבט" in soldier_notif.title
    assert "20.08.2026" in soldier_notif.title

    # Verify commander received notification with soldier's name
    commander_notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == commander.id, Notification.type == NotificationType.rank_advancement_soon
        )
    ).scalar_one()
    assert soldier.full_name in commander_notif.title
    assert "רבט" in commander_notif.title
    assert "20.08.2026" in commander_notif.title
