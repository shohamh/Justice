from __future__ import annotations

from unittest.mock import create_autospec

from sqlalchemy.orm import Session

from app.services import commander_dashboard as svc


def test_summary_cards_empty_subtree():
    """Empty subtree returns zeros."""
    session = create_autospec(Session)
    session.execute.return_value.scalar.return_value = 0
    session.execute.return_value.scalars.return_value.all.return_value = []
    session.execute.return_value.all.return_value = []
    result = svc.summary_cards(session, subtree_ids=[])
    assert result["approvals_pending"] == 0
    assert result["upcoming_duties_7d"] == 0
    assert result["unfilled_gaps"] == 0
    assert result["alerts_count"] == 0


def test_fairness_stats_empty():
    """No soldiers returns all-zero stats."""
    session = create_autospec(Session)
    result = svc.fairness_stats(session, subtree_ids=[])
    assert result["soldier_count"] == 0
    assert result["mean"] == 0.0


def test_potential_counts_no_soldiers():
    """Empty subtree returns labels with zero counts."""
    session = create_autospec(Session)
    result = svc.potential_counts(session, subtree_ids=[])
    assert len(result) == 5
    for item in result:
        assert item["count"] == 0


def test_upcoming_route_includes_status_field_for_draft(client, admin_session):
    from datetime import date, timedelta
    from decimal import Decimal
    from app.db.models import DutyAssignment, DutyLocation, DutyType
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="unit", name="upcoming_route_draft_test")
    cmd = create_soldier(admin_session, personal_number="7940101", role="commander")
    node.commander_id = cmd.id
    soldier = create_soldier(admin_session, personal_number="7940102", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_upcoming_route_draft", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_upcoming_route_draft")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    r = client.get("/api/command-dashboard/upcoming", headers=auth_headers(cmd))
    assert r.status_code == 200
    all_assignments = [a for day in r.json() for a in day["assignments"]]
    assert len(all_assignments) == 1
    assert all_assignments[0]["status"] == "algorithm_draft"


def test_active_commander_deputy_can_reach_dashboard(client, admin_session):
    import uuid
    from datetime import date
    from app.db.models import RoleDeputy
    from tests.helpers import auth_headers, create_node, create_soldier

    principal = create_soldier(admin_session, personal_number=f"cdash1_{uuid.uuid4().hex[:8]}", role="commander")
    create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"cdash2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    r = client.get("/api/command-dashboard/summary", headers=auth_headers(deputy))
    assert r.status_code == 200, r.text
