from __future__ import annotations

import uuid
from datetime import date

from app.db.models import DutyAssignment, DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_effective_duties_include_duty_type_name(client, admin_session):
    soldier = create_soldier(admin_session, personal_number=f"eff_{_uid()}")
    dtype = DutyType(name=f"שמירה_{_uid()}", score_per_day=1, active=True)
    loc = DutyLocation(name=f"loc_{_uid()}", base="בסיס")
    admin_session.add_all([dtype, loc])
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dtype.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
        start_time="08:00", end_time="20:00", status="published",
    ))
    admin_session.commit()

    resp = client.get(
        "/api/assignments/effective",
        params={"soldier_id": str(soldier.id)},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 200
    assert resp.json()[0]["duty_type_name"] == dtype.name
