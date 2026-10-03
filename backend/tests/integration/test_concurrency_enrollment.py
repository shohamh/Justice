"""C8/X1 — enrollment approve vs reject lose updates.

``approve_enrollment`` and ``reject_enrollment`` read the enrollment request
with ``session.get``, check ``status == 'pending'`` and write by primary key,
with no row lock. ``approve_enrollment`` also moves the soldier into the
requested node (``try_activate``).

Schedule reproduced here (two independent sessions = two commanders' requests):
  1. the rejecting request reads the enrollment request (status=pending);
  2. the approving request moves the soldier, sets approved and commits;
  3. the rejecting request resumes, sets rejected and commits.

Fixed (Task 3): both decisions lock the request with ``lock_request``
(``FOR UPDATE`` + fresh read) before the pending check. The late reject sees
``approved`` and fails with ``already_decided``.
"""
from __future__ import annotations

from app.db.models import Soldier, SoldierEnrollmentRequest
from app.services import enrollment as enrollment_service
from tests.helpers import create_node, create_soldier


def test_approve_and_reject_of_one_enrollment_cannot_both_succeed(race, admin_session):
    node = create_node(admin_session, level="branch", name="race-enroll-node")
    commander = create_soldier(admin_session, personal_number="race-enroll-cmd", role="commander")
    soldier = create_soldier(admin_session, personal_number="race-enroll-soldier")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id)
    admin_session.add(req)
    admin_session.commit()
    request_id = req.id

    late, early = race.stale_write(
        read=lambda s: s.get(SoldierEnrollmentRequest, request_id),
        write=lambda s, _row: enrollment_service.reject_enrollment(
            s, request_id=request_id, decider_id=commander.id, decision_note="no",
        ).status,
        decide=lambda s: enrollment_service.approve_enrollment(
            s, request_id=request_id, decider_id=commander.id, decision_note=None,
        ).status,
    )

    for outcome in (late, early):
        if not outcome.ok and not isinstance(outcome.error, enrollment_service.EnrollmentError):
            raise RuntimeError(f"decision crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    final_status = admin_session.get(SoldierEnrollmentRequest, request_id).status
    placed = admin_session.get(Soldier, soldier.id).hierarchy_node_id == node.id
    assert (early.ok, late.ok) == (True, False), (
        f"approve={early!r}, reject={late!r}; final status={final_status!r}, soldier placed in node={placed}"
    )
    assert (final_status, placed) == ("approved", True)
    assert str(late.error) == "already_decided"
