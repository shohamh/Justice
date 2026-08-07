from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyLocation, DutyType, RangeType
from tests.helpers import auth_headers, create_node, create_soldier


def test_ineligible_candidate_flagged_but_not_removed(client, admin_session):
    node = create_node(admin_session, level="branch", name="wc-node-1")
    dm = create_soldier(admin_session, personal_number="wc-dm-1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="wc-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="wc-weapon-duty", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    loc = DutyLocation(name="wc-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.commit()

    start = (date.today() + timedelta(days=10)).isoformat()
    end = (date.today() + timedelta(days=11)).isoformat()
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": start, "end_date": end, "required_count": 1,
    }, headers=auth_headers(dm))
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    assert resp.status_code == 200
    candidates = {c["soldier_id"]: c for c in resp.json()}
    assert str(soldier.id) in candidates
    cand = candidates[str(soldier.id)]
    assert cand["weapon_warning"] is True
    assert cand["blocked"] is False  # stays selectable, unlike constraint/assignment blocks


def test_eligible_candidate_has_no_warning(client, admin_session):
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_range_location

    node = create_node(admin_session, level="branch", name="wc-node-2")
    dm = create_soldier(admin_session, personal_number="wc-dm-2", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="wc-sol-2", hierarchy_node_id=node.id)
    dt = DutyType(
        name="wc-weapon-duty-2", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    loc = DutyLocation(name="wc-loc-2")
    admin_session.add_all([dt, loc])
    admin_session.commit()

    range_event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    add_range_assignment(admin_session, event=range_event, soldier_id=soldier.id, is_reserve=False)
    admin_session.commit()

    start = (date.today() + timedelta(days=10)).isoformat()
    end = (date.today() + timedelta(days=11)).isoformat()
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": start, "end_date": end, "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = shift_resp.json()["id"]

    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    cand = {c["soldier_id"]: c for c in resp.json()}[str(soldier.id)]
    assert cand["weapon_warning"] is False
