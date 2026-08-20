from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, select

from app.db.models import (
    CommanderNotificationScope,
    DutyManagerScope,
    HierarchyLevelType,
    Notification,
    NotificationType,
    RoleDeputy,
)
from app.services.authority import REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY
from app.services.notifications import (
    cascade_to_commanders,
    notify_duty_managers_in_scope,
    notify_duty_managers_of_request,
)
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _notif_recipient_ids(session, *, reference_id) -> set:
    rows = session.execute(
        select(Notification.soldier_id).where(Notification.reference_id == reference_id)
    ).scalars().all()
    return set(rows)


def test_cascade_to_commanders_also_notifies_active_deputy(admin_session):
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"a_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"b_{_uid()}", role="commander")
    admin_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=commander.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    cascade_to_commanders(
        admin_session, type=NotificationType.assignment_created, title="t", body=None,
        reference_type="duty_assignment", reference_id=ref_id, actor_id=None,
        original_soldier_id=soldier.id,
    )
    admin_session.commit()

    recipients = _notif_recipient_ids(admin_session, reference_id=ref_id)
    assert commander.id in recipients
    assert deputy.id in recipients


def test_cascade_to_commanders_dedupes_deputy_notified_via_two_principals(admin_session):
    """A soldier who is an active deputy for TWO different commanders that
    both match in a single cascade_to_commanders run must get exactly one
    notification, not one per principal."""
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"j_{_uid()}", hierarchy_node_id=node.id)
    commander_a = create_soldier(admin_session, personal_number=f"k_{_uid()}", role="commander")
    commander_b = create_soldier(admin_session, personal_number=f"l_{_uid()}", role="commander")
    admin_session.add(CommanderNotificationScope(commander_id=commander_a.id, hierarchy_node_id=node.id))
    admin_session.add(CommanderNotificationScope(commander_id=commander_b.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"m_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=commander_a.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.add(RoleDeputy(
        principal_id=commander_b.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    cascade_to_commanders(
        admin_session, type=NotificationType.assignment_created, title="t", body=None,
        reference_type="duty_assignment", reference_id=ref_id, actor_id=None,
        original_soldier_id=soldier.id,
    )
    admin_session.commit()

    deputy_notif_count = len(admin_session.execute(
        select(Notification.id).where(
            Notification.reference_id == ref_id, Notification.soldier_id == deputy.id
        )
    ).scalars().all())
    assert deputy_notif_count == 1, (
        f"deputy for two matched commanders got {deputy_notif_count} notifications, expected exactly 1"
    )


def test_notify_duty_managers_in_scope_also_notifies_active_deputy(admin_session):
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"d_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"e_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"f_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=dm.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    notify_duty_managers_in_scope(
        admin_session, soldier_id=soldier.id, type=NotificationType.swap_pending_approval,
        title="t", reference_type="swap_request", reference_id=ref_id,
    )
    admin_session.commit()

    recipients = _notif_recipient_ids(admin_session, reference_id=ref_id)
    assert dm.id in recipients
    assert deputy.id in recipients


def test_notify_duty_managers_of_request_also_notifies_active_deputy(admin_session):
    # REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY (the level notify_duty_managers_of_request
    # actually checks against — a fixed module constant, not a setting) is the
    # Hebrew string "מרכז", used directly as a HierarchyLevelType.key lookup in
    # dm_scope_covers_level. The shared English-keyed level defaults seeded by
    # conftest's admin_session (department/branch/group/...) have no key equal
    # to "מרכז" itself, so dm_scope_covers_level would never find a rank and no
    # DM would ever qualify. Replace them with a minimal Hebrew-keyed hierarchy,
    # as test_notifications_dm.py / test_exemption_requests.py do.
    admin_session.execute(delete(HierarchyLevelType))
    admin_session.add(HierarchyLevelType(
        key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, label=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, rank=1
    ))
    admin_session.add(HierarchyLevelType(key="פלוגה", label="פלוגה", rank=2))
    admin_session.flush()

    node = create_node(admin_session, level=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"g_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"h_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"i_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=dm.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    notify_duty_managers_of_request(
        admin_session, soldier_id=soldier.id, type=NotificationType.exemption_request_pending,
        title="t", reference_type="exemption_request", reference_id=ref_id,
    )
    admin_session.commit()

    recipients = _notif_recipient_ids(admin_session, reference_id=ref_id)
    assert dm.id in recipients
    assert deputy.id in recipients
