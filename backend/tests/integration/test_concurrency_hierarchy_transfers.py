"""C8/H2 — hierarchy transfer approve vs reject lose updates.

``approve_request`` and ``reject_request`` read the transfer request with a
plain ``session.get``, check ``status == 'pending'`` and write by primary key.
Neither locks the request, so a decision that read ``pending`` before another
decision committed still succeeds.

Schedule reproduced here (two independent sessions = two approvers' requests):
  1. the rejecting request reads the transfer request (status=pending);
  2. the approving request moves the soldier, sets approved and commits;
  3. the rejecting request resumes, sets rejected and commits.
"""
from __future__ import annotations

import pytest

from app.db.models import HierarchyTransferRequest, Soldier
from app.services import hierarchy_transfers as transfer_service
from tests.helpers import create_node, create_soldier


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="C8/H2: approve and reject of one transfer request both succeed (no lock on the request)",
)
def test_approve_and_reject_of_one_transfer_cannot_both_succeed(race, admin_session):
    from_node = create_node(admin_session, level="branch", name="race-transfer-from")
    to_node = create_node(admin_session, level="branch", name="race-transfer-to")
    admin = create_soldier(admin_session, personal_number="race-transfer-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="race-transfer-soldier", hierarchy_node_id=from_node.id)
    req = HierarchyTransferRequest(soldier_id=soldier.id, to_node_id=to_node.id, requested_by=admin.id,
                                   from_node_id=from_node.id)
    admin_session.add(req)
    admin_session.commit()
    request_id = req.id

    late, early = race.stale_write(
        read=lambda s: s.get(HierarchyTransferRequest, request_id),
        write=lambda s, _row: transfer_service.reject_request(s, request_id=request_id, actor_id=admin.id).status,
        decide=lambda s: transfer_service.approve_request(s, request_id=request_id, actor_id=admin.id).status,
    )

    for outcome in (late, early):
        if not outcome.ok and not isinstance(outcome.error, transfer_service.HierarchyTransferError):
            raise RuntimeError(f"decision crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    final_status = admin_session.get(HierarchyTransferRequest, request_id).status
    final_node = admin_session.get(Soldier, soldier.id).hierarchy_node_id
    moved = final_node == to_node.id
    assert (early.ok, late.ok) == (True, False), (
        f"approve={early!r}, reject={late!r}; final status={final_status!r}, soldier moved={moved}"
    )
    assert (final_status, moved) == ("approved", True)
