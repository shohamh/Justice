"""C8/P3 — soldier field update approve vs reject lose updates.

``approve_field_update`` locks the update row (``FOR UPDATE`` +
``populate_existing``), but ``reject_field_update`` checks the status of the
row object the route loaded earlier and writes ``rejected`` unconditionally.

Schedule reproduced here (two independent sessions = two approvers' requests):
  1. the rejecting request loads the field update (status=pending);
  2. the approving request locks it, applies the new value to the soldier,
     sets approved and commits;
  3. the rejecting request resumes, sets rejected and commits.
"""
from __future__ import annotations

import pytest

from app.db.models import Soldier, SoldierFieldUpdate
from app.services import soldiers as soldier_service
from tests.helpers import create_soldier

_NEW_PHONE = "0501112233"


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="C8/P3: reject_field_update overwrites an approval committed after the route read the row",
)
def test_reject_cannot_overwrite_a_committed_approval(race, admin_session):
    admin = create_soldier(admin_session, personal_number="race-sfu-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="race-sfu-soldier")
    update = SoldierFieldUpdate(soldier_id=soldier.id, field_name="phone", new_value=_NEW_PHONE, status="pending")
    admin_session.add(update)
    admin_session.commit()
    update_id = update.id

    late, early = race.stale_write(
        read=lambda s: s.get(SoldierFieldUpdate, update_id),
        write=lambda s, row: soldier_service.reject_field_update(s, update=row, actor_id=admin.id).status,
        decide=lambda s: soldier_service.approve_field_update(
            s, update=s.get(SoldierFieldUpdate, update_id), actor_id=admin.id,
        ).status,
    )

    for outcome in (late, early):
        if not outcome.ok and not isinstance(outcome.error, soldier_service.SoldierError):
            raise RuntimeError(f"decision crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    final_status = admin_session.get(SoldierFieldUpdate, update_id).status
    phone = admin_session.get(Soldier, soldier.id).phone
    assert (early.ok, late.ok) == (True, False), (
        f"approve={early!r}, reject={late!r}; final status={final_status!r}, soldier.phone={phone!r}"
    )
    assert (final_status, phone) == ("approved", _NEW_PHONE)
