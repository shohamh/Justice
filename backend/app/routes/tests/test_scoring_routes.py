from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType
from app.services.algorithm_bridge import load_soldier_inputs
from tests.helpers import auth_headers, create_soldier


def test_eligibility_groups_returns_summary_without_soldier_list(
    client: TestClient, admin_session: Session
):
    """Test that /scoring/eligibility-groups returns summary data without per-soldier details."""
    # Create a duty type
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.00"), active=True)
    admin_session.add(dt)
    admin_session.flush()

    # Create a soldier eligible for this duty type
    soldier = create_soldier(admin_session, personal_number="test_soldier_001")
    admin_session.commit()

    # Create an admin to call the endpoint
    admin = create_soldier(admin_session, personal_number="admin_001", role="admin")
    admin_session.commit()

    # Call the endpoint
    resp = client.get("/api/scoring/eligibility-groups", headers=auth_headers(admin))

    # Verify the response
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)

    # Find the group containing the duty type "שמירה"
    group = next((g for g in body if "שמירה" in g["duty_type_names"]), None)
    assert group is not None, "Should find a group containing 'שמירה'"

    # Verify the group has the expected fields
    assert "duty_type_ids" in group
    assert "duty_type_names" in group
    assert "soldier_count" in group

    # Verify the group does NOT have per-soldier details
    assert "soldiers" not in group
    assert "burden_share" not in group

    # Verify the soldier count is at least 1
    assert group["soldier_count"] >= 1
