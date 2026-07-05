from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType, ExemptionType, SoldierExemption
from tests.helpers import auth_headers, create_node, create_soldier


def test_potential_exemptions_array_populated_when_authorized(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="division", name="div-pot-1")
    cmd = create_soldier(admin_session, personal_number="5700001", role="commander")
    cmd.rank = "רסן"  # רסן is in RANKS_RASAN_AND_ABOVE, required for POTENTIAL_READ
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5700002", hierarchy_node_id=node.id)
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
    cmd = create_soldier(admin_session, personal_number="5700003", role="commander")
    cmd.rank = "רסן"
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5700004", hierarchy_node_id=node.id)

    admin_user = create_soldier(admin_session, personal_number="5700005", role="admin")

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
