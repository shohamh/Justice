from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    PotentialModifier,
    SoldierExemption,
)
from tests.helpers import auth_headers, create_node, create_soldier


def test_burden_share_gap_endpoint_returns_all_nodes(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="Effort Gap API Co")
    admin = create_soldier(admin_session, personal_number="5700001", role="admin")

    resp = client.get("/api/potential/burden-share-gap", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert str(node.id) in node_ids
    entry = next(n for n in body["nodes"] if n["node_id"] == str(node.id))
    assert "sibling_gap" in entry
    assert "global_gap" in entry


def test_burden_share_gap_endpoint_scopes_to_duty_manager(client: TestClient, admin_session: Session):
    in_scope_node = create_node(admin_session, level="unit", name="In Scope Co")
    out_of_scope_node = create_node(admin_session, level="unit", name="Out Of Scope Co")
    dm = create_soldier(
        admin_session,
        personal_number="5700002",
        role="duty_manager",
        hierarchy_node_id=in_scope_node.id,
    )

    resp = client.get("/api/potential/burden-share-gap", headers=auth_headers(dm))
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert str(in_scope_node.id) in node_ids
    assert str(out_of_scope_node.id) not in node_ids


def test_potential_exemptions_array_populated_when_authorized(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="division", name="div-pot-1")
    cmd = create_soldier(admin_session, personal_number="5700010", role="commander")
    cmd.rank = "רסן"  # רסן is in RANKS_RASAN_AND_ABOVE, required for POTENTIAL_READ
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5700011", hierarchy_node_id=node.id)
    dt = DutyType(name="שמירה-pot1", score_per_day=Decimal("1.00"))
    et = ExemptionType(name="פטור-פוט1", is_global=True)
    admin_session.add_all([dt, et])
    admin_session.flush()
    ex = SoldierExemption(
        soldier_id=target.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    )
    admin_session.add(ex)
    admin_session.commit()
    admin_session.refresh(ex)

    r = client.get(
        "/api/potential", params={"node_id": str(node.id)}, headers=auth_headers(cmd),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(s for s in body["soldiers"] if s["soldier_id"] == str(target.id))
    assert row["exemptions"] is not None
    assert len(row["exemptions"]) == 1
    item = row["exemptions"][0]
    assert item["id"] == str(ex.id)
    assert item["exemption_type_name"] == "פטור-פוט1"
    assert item["is_global"] is True
    assert item["end_date"] is None


def test_potential_exemptions_array_null_when_not_viewing_private(client: TestClient, admin_session: Session):
    # Create a division with a commander; the commander can see their own node's potential
    # and exemptions (as they are in scope as commander). But if we query via an admin user
    # who is NOT a commander or DM, exemptions should be None.
    node = create_node(admin_session, level="division", name="div-pot-2")
    cmd = create_soldier(admin_session, personal_number="5700012", role="commander")
    cmd.rank = "רסן"
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5700013", hierarchy_node_id=node.id)

    admin_user = create_soldier(admin_session, personal_number="5700014", role="admin")

    dt = DutyType(name="שמירה-pot2", score_per_day=Decimal("1.00"))
    et = ExemptionType(name="פטור-פוט2", is_global=True)
    admin_session.add_all([dt, et])
    admin_session.flush()
    admin_session.add(SoldierExemption(soldier_id=target.id, exemption_type_id=et.id, start_date=date(2026, 1, 1)))
    admin_session.commit()

    # Query via admin (no commander/DM scope): exemptions should be None even though they're authorized to view endpoint
    r = client.get(
        "/api/potential", params={"node_id": str(node.id)}, headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(s for s in body["soldiers"] if s["soldier_id"] == str(target.id))
    assert row["exemptions"] is None


def test_potential_summary_matches_full_home_aggregates_for_authorized_descendants(
    client: TestClient, admin_session: Session
):
    reference_date = date(2026, 9, 15)
    root = create_node(admin_session, level="division", name="Potential Summary Root")
    commander = create_soldier(admin_session, personal_number="5700020", role="commander")
    commander.rank = "רסן"
    root.commander_id = commander.id
    child = create_node(admin_session, level="team", name="Potential Summary Child", parent=root)
    admin_session.commit()

    partial_soldier = create_soldier(
        admin_session, personal_number="5700021", hierarchy_node_id=child.id
    )
    globally_exempt_soldier = create_soldier(
        admin_session, personal_number="5700022", hierarchy_node_id=child.id
    )
    departed_soldier = create_soldier(
        admin_session, personal_number="5700023", hierarchy_node_id=child.id
    )
    departed_soldier.left_at = date(2026, 9, 14)

    first_duty = DutyType(name="Potential Summary First", score_per_day=Decimal("1.00"))
    second_duty = DutyType(name="Potential Summary Second", score_per_day=Decimal("1.00"))
    partial_type = ExemptionType(name="Potential Summary Partial")
    global_type = ExemptionType(name="Potential Summary Global", is_global=True)
    admin_session.add_all([first_duty, second_duty, partial_type, global_type])
    admin_session.flush()
    admin_session.add(ExemptionDutyTypeMap(
        exemption_type_id=partial_type.id, duty_type_id=first_duty.id
    ))
    admin_session.add_all([
        SoldierExemption(
            soldier_id=partial_soldier.id,
            exemption_type_id=partial_type.id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        ),
        SoldierExemption(
            soldier_id=globally_exempt_soldier.id,
            exemption_type_id=global_type.id,
            start_date=date(2026, 9, 1),
            end_date=None,
        ),
        PotentialModifier(
            hierarchy_node_id=child.id,
            delta=2,
            reason="Summary parity fixture",
            start_date=reference_date,
            end_date=reference_date,
        ),
    ])
    admin_session.commit()

    params = {"node_id": str(root.id), "reference_date": reference_date.isoformat()}
    full_response = client.get("/api/potential", params=params, headers=auth_headers(commander))
    summary_response = client.get(
        "/api/potential/summary", params=params, headers=auth_headers(commander)
    )

    assert full_response.status_code == 200, full_response.text
    assert summary_response.status_code == 200, summary_response.text
    full = full_response.json()
    summary = summary_response.json()
    assert full["raw_eligible_count"] == 1
    assert full["total_soldiers"] == 2
    assert full["partial_exemption_count"] == 1
    assert full["final_potential"] == 3
    assert set(summary) == {
        "node_id",
        "as_of",
        "raw_eligible_count",
        "modifier_total",
        "final_potential",
    }
    assert summary == {
        "node_id": full["node_id"],
        "as_of": full["as_of"],
        "raw_eligible_count": full["raw_eligible_count"],
        "modifier_total": sum(modifier["delta"] for modifier in full["modifiers"]),
        "final_potential": full["final_potential"],
    }


def test_potential_summary_preserves_target_node_authorization(
    client: TestClient, admin_session: Session
):
    node = create_node(admin_session, level="division", name="Protected Potential Summary")
    user = create_soldier(admin_session, personal_number="5700024", role="soldier")

    full_response = client.get(
        "/api/potential", params={"node_id": str(node.id)}, headers=auth_headers(user)
    )
    summary_response = client.get(
        "/api/potential/summary", params={"node_id": str(node.id)}, headers=auth_headers(user)
    )

    assert full_response.status_code == 403
    assert summary_response.status_code == full_response.status_code
