from __future__ import annotations

from decimal import Decimal

from app.db.models import (
    DutyAssignment, DutyLocation, DutyType, ExemptionDutyTypeMap,
    ExemptionType, SoldierExemption,
)
from tests.helpers import auth_headers, create_node, create_soldier


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
