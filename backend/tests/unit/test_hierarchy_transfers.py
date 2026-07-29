from __future__ import annotations

import pytest


def test_create_request_does_not_move_soldier_immediately(admin_session):
    from app.services.hierarchy_transfers import create_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit")
    dst = create_node(admin_session, level="unit", name="dst_unit")
    soldier = create_soldier(admin_session, personal_number="7990001", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990002", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()

    assert req.status == "pending"
    assert soldier.hierarchy_node_id == src.id  # unchanged until approved


def test_approve_request_moves_soldier(admin_session):
    from app.services.hierarchy_transfers import approve_request, create_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit2")
    dst = create_node(admin_session, level="unit", name="dst_unit2")
    soldier = create_soldier(admin_session, personal_number="7990003", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990004", role="commander")
    approver = create_soldier(admin_session, personal_number="7990005", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()
    approve_request(admin_session, request_id=req.id, actor_id=approver.id)
    admin_session.commit()

    assert req.status == "approved"
    assert soldier.hierarchy_node_id == dst.id


def test_reject_request_leaves_soldier_in_place_and_notifies_requester(admin_session):
    from sqlalchemy import select

    from app.db.models import Notification, NotificationType
    from app.services.hierarchy_transfers import create_request, reject_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit3")
    dst = create_node(admin_session, level="unit", name="dst_unit3")
    soldier = create_soldier(admin_session, personal_number="7990006", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990007", role="commander")
    approver = create_soldier(admin_session, personal_number="7990008", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()
    reject_request(admin_session, request_id=req.id, actor_id=approver.id, decision_note="no room")
    admin_session.commit()

    assert req.status == "rejected"
    assert soldier.hierarchy_node_id == src.id
    notif = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == requester.id,
            Notification.type == NotificationType.transfer_request_rejected,
        )
    ).scalar_one_or_none()
    assert notif is not None


def test_create_request_raises_for_missing_soldier(admin_session):
    import uuid

    from app.services.hierarchy_transfers import HierarchyTransferError, create_request
    from tests.helpers import create_node, create_soldier

    dst = create_node(admin_session, level="unit", name="dst_unit4")
    requester = create_soldier(admin_session, personal_number="7990009", role="commander")

    with pytest.raises(HierarchyTransferError):
        create_request(admin_session, soldier_id=uuid.uuid4(), to_node_id=dst.id, requested_by=requester.id)


def test_approve_twice_raises_not_pending(admin_session):
    from app.services.hierarchy_transfers import HierarchyTransferError, approve_request, create_request
    from tests.helpers import create_node, create_soldier

    src = create_node(admin_session, level="unit", name="src_unit5")
    dst = create_node(admin_session, level="unit", name="dst_unit5")
    soldier = create_soldier(admin_session, personal_number="7990010", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="7990011", role="commander")
    approver = create_soldier(admin_session, personal_number="7990012", role="commander")

    req = create_request(admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id)
    admin_session.commit()
    approve_request(admin_session, request_id=req.id, actor_id=approver.id)
    admin_session.commit()

    with pytest.raises(HierarchyTransferError):
        approve_request(admin_session, request_id=req.id, actor_id=approver.id)


def test_list_pending_for_approver_scopes_by_destination_node(admin_session):
    from app.services.hierarchy_transfers import create_request, list_pending_for_approver
    from tests.helpers import create_node, create_soldier

    approver = create_soldier(admin_session, personal_number="7990013", role="commander")
    dst = create_node(admin_session, level="unit", name="dst_unit6", commander_id=approver.id)
    other_dst = create_node(admin_session, level="unit", name="dst_unit7")
    soldier = create_soldier(admin_session, personal_number="7990014")
    soldier2 = create_soldier(admin_session, personal_number="7990015")
    requester = create_soldier(admin_session, personal_number="7990016", role="commander")

    req_for_approver = create_request(
        admin_session, soldier_id=soldier.id, to_node_id=dst.id, requested_by=requester.id
    )
    create_request(admin_session, soldier_id=soldier2.id, to_node_id=other_dst.id, requested_by=requester.id)
    admin_session.commit()

    pending = list_pending_for_approver(admin_session, approver_id=approver.id)

    assert [r.id for r in pending] == [req_for_approver.id]


def test_create_request_rejects_unknown_to_node(admin_session):
    import uuid

    from app.services.hierarchy_transfers import HierarchyTransferError, create_request
    from tests.helpers import create_soldier

    s = create_soldier(admin_session, personal_number="7600001")
    with pytest.raises(HierarchyTransferError, match="to_node_not_found"):
        create_request(
            admin_session, soldier_id=s.id, to_node_id=uuid.uuid4(), requested_by=s.id,
        )


def test_create_request_succeeds_for_real_node(admin_session):
    from app.services.hierarchy_transfers import create_request
    from tests.helpers import create_node, create_soldier

    s = create_soldier(admin_session, personal_number="7600002")
    node = create_node(admin_session, level="unit", name="u1")
    req = create_request(admin_session, soldier_id=s.id, to_node_id=node.id, requested_by=s.id)
    admin_session.commit()
    assert req.to_node_id == node.id
