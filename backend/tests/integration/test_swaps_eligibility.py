from __future__ import annotations

from decimal import Decimal

from app.db.models import (
    DutyAssignment, DutyLocation, DutyType, ExemptionDutyTypeMap,
    ExemptionType, SoldierExemption,
)
from tests.helpers import auth_headers, create_node, create_soldier


def _setup_targets(session, pn: str):
    node = create_node(session, level="branch", name=f"n_et_{pn}")
    requester = create_soldier(session, personal_number=f"et_req_{pn}", hierarchy_node_id=node.id)
    target = create_soldier(session, personal_number=f"et_tgt_{pn}", hierarchy_node_id=node.id)
    dt = DutyType(name=f"dt_et_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_et_{pn}")
    session.add(dt); session.add(loc); session.flush()
    assignment = DutyAssignment(
        soldier_id=requester.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2030-03-10",
        end_date="2030-03-10",
        status="published",
    )
    session.add(assignment); session.flush()
    session.commit()
    return requester, target, assignment


def test_eligible_targets_route_returns_candidate(client, admin_session):
    requester, target, assignment = _setup_targets(admin_session, "001")

    resp = client.get(
        f"/api/swaps/eligible-targets?duty_assignment_id={assignment.id}",
        headers=auth_headers(requester),
    )
    assert resp.status_code == 200
    results = resp.json()
    ids = [r["soldier_id"] for r in results]
    assert str(target.id) in ids
    assert str(requester.id) not in ids
    match = next(r for r in results if r["soldier_id"] == str(target.id))
    assert match["hierarchy_distance"] == 0


def test_eligible_targets_route_excludes_exempt_candidate(client, admin_session):
    requester, target, assignment = _setup_targets(admin_session, "002")
    et = ExemptionType(name="global_et_et_002", is_global=True)
    admin_session.add(et); admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=target.id, exemption_type_id=et.id, start_date="2025-01-01", end_date=None
        )
    )
    admin_session.commit()

    resp = client.get(
        f"/api/swaps/eligible-targets?duty_assignment_id={assignment.id}",
        headers=auth_headers(requester),
    )
    assert resp.status_code == 200
    ids = [r["soldier_id"] for r in resp.json()]
    assert str(target.id) not in ids


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_se_{pn}")
    actor = create_soldier(session, personal_number=f"se_actor_{pn}", hierarchy_node_id=node.id)
    target = create_soldier(session, personal_number=f"se_target_{pn}", hierarchy_node_id=node.id)
    dt = DutyType(name=f"dt_se_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_se_{pn}")
    session.add(dt); session.add(loc); session.flush()
    assignment = DutyAssignment(
        soldier_id=actor.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2030-01-10",
        end_date="2030-01-10",
        status="published",
    )
    session.add(assignment); session.flush()
    session.commit()
    return actor, target, dt, assignment


def test_eligible_duties_no_exemption(client, admin_session):
    actor, target, _dt, assignment = _setup(admin_session, "001")

    resp = client.get(
        f"/api/swaps/eligible-duties?target_soldier_id={target.id}",
        headers=auth_headers(actor),
    )
    assert resp.status_code == 200
    results = resp.json()
    match = next((r for r in results if r["assignment_id"] == str(assignment.id)), None)
    assert match is not None
    assert match["eligible"] is True


def test_eligible_duties_exemption(client, admin_session):
    actor, target, dt, assignment = _setup(admin_session, "002")

    # Create a global exemption type and grant it to target
    et = ExemptionType(name=f"global_et_002", is_global=True)
    admin_session.add(et); admin_session.flush()
    ex = SoldierExemption(
        soldier_id=target.id,
        exemption_type_id=et.id,
        start_date="2025-01-01",
        end_date=None,
    )
    admin_session.add(ex); admin_session.commit()

    resp = client.get(
        f"/api/swaps/eligible-duties?target_soldier_id={target.id}",
        headers=auth_headers(actor),
    )
    assert resp.status_code == 200
    results = resp.json()
    match = next((r for r in results if r["assignment_id"] == str(assignment.id)), None)
    assert match is not None
    assert match["eligible"] is False
    assert "פטור" in match["reason"]
