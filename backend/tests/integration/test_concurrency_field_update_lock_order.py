"""C9 — deadlock between ``submit_field_update`` and ``approve_field_update`` (audit inventory P4).

``submit_field_update`` locks the soldier (``FOR UPDATE``) and then UPDATEs the
soldier's older pending field-update rows to ``superseded``/``cancelled``.
``approve_field_update`` locks the field-update row (``FOR UPDATE``) and then
UPDATEs the soldier at flush. The two take the same pair of rows in opposite
order.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. request A approves pending update U and holds its row lock;
  2. request B submits a new value for the same field and holds the soldier lock;
  3. A writes the soldier (waits on B) and B supersedes U (waits on A).
PostgreSQL detects the cycle and aborts one request with ``DeadlockDetected``,
which nothing maps, so the user sees a 500.

Fixed (Task 4): ``approve_field_update`` locks the soldier (``FOR NO KEY
UPDATE``) before the field-update row, the same soldier -> update order as
submit. The submitter blocks on the soldier lock, so the approver's wait for it
times out, the approval commits, and the submit then files a new pending row.
"""
from __future__ import annotations

from app.db.models import Soldier, SoldierFieldUpdate
from app.services import soldiers as soldier_service
from tests.helpers import create_soldier

_APPROVED_PHONE = "0501112233"
_RESUBMITTED_PHONE = "0504445566"


def test_concurrent_submit_and_approve_of_one_field_do_not_deadlock(race, admin_session):
    admin = create_soldier(admin_session, personal_number="race-lo-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="race-lo-soldier")
    update = SoldierFieldUpdate(soldier_id=soldier.id, field_name="phone", new_value=_APPROVED_PHONE, status="pending")
    admin_session.add(update)
    admin_session.commit()
    update_id, soldier_id, admin_id = update.id, soldier.id, admin.id

    approver_locked_update = race.signal("approver holds the field-update row lock")
    submitter_locked_soldier = race.signal("submitter holds the soldier row lock")

    def approve():
        s = race.session()
        row = s.get(SoldierFieldUpdate, update_id)

        def _after_update_lock():
            approver_locked_update.set()
            submitter_locked_soldier.wait()

        race.pause_after_select(s, SoldierFieldUpdate, _after_update_lock)
        result = soldier_service.approve_field_update(s, update=row, actor_id=admin_id).status
        s.commit()
        return result

    def submit():
        approver_locked_update.wait()
        s = race.session()
        race.pause_after_select(s, Soldier, submitter_locked_soldier.set)
        result = soldier_service.submit_field_update(
            s, soldier_id=soldier_id, field_name="phone", new_value=_RESUBMITTED_PHONE, actor_id=soldier_id,
        ).status
        s.commit()
        return result

    approved, submitted = race.run(approve, submit)

    admin_session.expire_all()
    rows = {r.new_value: r.status for r in admin_session.query(SoldierFieldUpdate).filter_by(soldier_id=soldier_id)}
    assert approved.ok and submitted.ok, f"approve={approved!r}, submit={submitted!r}; rows={rows}"
    assert approved.value == "approved"
    assert admin_session.get(Soldier, soldier_id).phone == _APPROVED_PHONE
    assert rows == {_APPROVED_PHONE: "approved", _RESUBMITTED_PHONE: "pending"}
