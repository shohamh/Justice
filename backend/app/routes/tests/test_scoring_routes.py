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


def test_eligibility_groups_service_matches_fairness_components_projection(
    admin_session: Session,
):
    """The lightweight grouping path must yield exactly the components the full
    fairness view reports (same groups, order, counts), minus per-soldier detail."""
    from app.services import scoring as svc

    open_type = DutyType(name="שמירה", score_per_day=Decimal("1.00"), active=True)
    gated_type = DutyType(
        name="מבצעי",
        score_per_day=Decimal("1.00"),
        active=True,
        requirements={"requires_mitvahim": True},
    )
    admin_session.add_all([open_type, gated_type])
    admin_session.flush()
    # Neither soldier has a recent mitvahim, so the gated type excludes both and
    # they connect only through the open type; the third has no eligibility gap.
    for number in ("elig_a", "elig_b", "elig_c"):
        create_soldier(admin_session, personal_number=number)
    admin_session.commit()

    full = svc.fairness_components(admin_session)
    expected = [
        {
            "duty_type_ids": c["duty_type_ids"],
            "duty_type_names": c["duty_type_names"],
            "soldier_count": c["soldier_count"],
        }
        for c in full["components"]
    ]

    assert expected, "fixture should produce at least one component"
    assert svc.eligibility_groups(admin_session) == expected
