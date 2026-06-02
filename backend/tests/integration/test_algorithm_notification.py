from __future__ import annotations

import time
from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType, Notification, NotificationType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt); session.add(loc); session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2027-04-01",
        end_date="2027-04-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def test_notification_created_when_job_completes(client, admin_session):
    dm, shift = _setup(admin_session, "alg_notif_001")
    create_soldier(admin_session, personal_number="alg_notif_001s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202
    job_id = create_resp.json()["id"]

    # Poll until done or failed
    poll = None
    for _ in range(20):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    final_status = poll.json()["status"]
    assert final_status in ("done", "failed")

    # Check notification was created for the dm
    admin_session.expire_all()
    notif = admin_session.query(Notification).filter(
        Notification.soldier_id == dm.id,
        Notification.reference_type == "algorithm_job",
    ).first()

    assert notif is not None
    assert str(notif.reference_id) == job_id
    if final_status == "done":
        assert notif.type == NotificationType.algorithm_job_done
        assert "הצעות" in notif.title
    else:
        assert notif.type == NotificationType.algorithm_job_failed
