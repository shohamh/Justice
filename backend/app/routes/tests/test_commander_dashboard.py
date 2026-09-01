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


def test_commander_who_is_also_deputy_sees_own_node(client, admin_session):
    """A real commander of node M who is also an active deputy for a
    principal commanding node N must land on their OWN dashboard (M), not
    have it silently swapped for the deputized node (N) or an arbitrary
    min(M, N)."""
    import uuid
    from datetime import date
    from app.db.models import DutyLocation, DutyType, HierarchyNode, RoleDeputy
    from decimal import Decimal
    from tests.helpers import auth_headers, create_node, create_soldier

    other_principal = create_soldier(
        admin_session, personal_number=f"cdash3_{uuid.uuid4().hex[:8]}", role="commander"
    )
    own_node = create_node(
        admin_session, level="group", name=f"own_{uuid.uuid4().hex[:8]}"
    )
    commander_who_is_deputy = create_soldier(
        admin_session, personal_number=f"cdash4_{uuid.uuid4().hex[:8]}", role="commander"
    )
    own_node.commander_id = commander_who_is_deputy.id
    admin_session.flush()
    create_node(
        admin_session,
        level="group",
        name=f"other_{uuid.uuid4().hex[:8]}",
        commander_id=other_principal.id,
    )
    admin_session.add(RoleDeputy(
        principal_id=other_principal.id, deputy_id=commander_who_is_deputy.id,
        role="commander", start_date=date.today(), end_date=date.today(),
    ))
    # Distinguishing marker: a duty type/location/assignment only visible
    # under the soldier's OWN node's subtree.
    marker_soldier = create_soldier(
        admin_session, personal_number=f"cdash5_{uuid.uuid4().hex[:8]}", hierarchy_node_id=own_node.id
    )
    dt = DutyType(name=f"dt_own_node_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1"))
    loc = DutyLocation(name=f"loc_own_node_{uuid.uuid4().hex[:8]}")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.commit()

    r = client.get("/api/command-dashboard/soldiers", headers=auth_headers(commander_who_is_deputy))
    assert r.status_code == 200, r.text
    ids = {s["id"] for s in r.json()}
    assert str(marker_soldier.id) in ids, (
        "commander who is also a deputy must see their OWN command's soldiers, "
        "not a swapped/arbitrary node"
    )


def test_duty_manager_dashboard_uses_authorized_scope_and_not_other_nodes(client, admin_session):
    import uuid
    from app.db.models import DutyManagerScope
    from tests.helpers import auth_headers, create_node, create_soldier

    scoped_node = create_node(admin_session, level="group", name=f"dm_scope_{uuid.uuid4().hex[:8]}")
    other_node = create_node(admin_session, level="group", name=f"dm_other_{uuid.uuid4().hex[:8]}")
    dm = create_soldier(
        admin_session,
        personal_number=f"cdash_dm_{uuid.uuid4().hex[:8]}",
        role="duty_manager",
    )
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=scoped_node.id))
    scoped_soldier = create_soldier(
        admin_session,
        personal_number=f"cdash_dm_in_{uuid.uuid4().hex[:8]}",
        hierarchy_node_id=scoped_node.id,
    )
    other_soldier = create_soldier(
        admin_session,
        personal_number=f"cdash_dm_out_{uuid.uuid4().hex[:8]}",
        hierarchy_node_id=other_node.id,
    )
    admin_session.commit()

    response = client.get(
        f"/api/command-dashboard/soldiers?node_id={other_node.id}",
        headers=auth_headers(dm),
    )

    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()}
    assert str(scoped_soldier.id) in ids
    assert str(other_soldier.id) not in ids


def test_deputy_duty_manager_dashboard_uses_principal_scope(client, admin_session):
    import uuid
    from datetime import date
    from app.db.models import DutyManagerScope, RoleDeputy
    from tests.helpers import auth_headers, create_node, create_soldier

    scoped_node = create_node(admin_session, level="group", name=f"dm_deputy_{uuid.uuid4().hex[:8]}")
    principal = create_soldier(
        admin_session,
        personal_number=f"cdash_dm_principal_{uuid.uuid4().hex[:8]}",
        role="duty_manager",
    )
    deputy = create_soldier(
        admin_session,
        personal_number=f"cdash_dm_deputy_{uuid.uuid4().hex[:8]}",
        role="soldier",
    )
    admin_session.add(DutyManagerScope(duty_manager_id=principal.id, hierarchy_node_id=scoped_node.id))
    admin_session.add(
        RoleDeputy(
            principal_id=principal.id,
            deputy_id=deputy.id,
            role="duty_manager",
            start_date=date.today(),
            end_date=date.today(),
        )
    )
    scoped_soldier = create_soldier(
        admin_session,
        personal_number=f"cdash_dm_deputy_in_{uuid.uuid4().hex[:8]}",
        hierarchy_node_id=scoped_node.id,
    )
    admin_session.commit()

    response = client.get("/api/command-dashboard/soldiers", headers=auth_headers(deputy))

    assert response.status_code == 200, response.text
    assert str(scoped_soldier.id) in {item["id"] for item in response.json()}


def test_regular_soldier_cannot_access_command_dashboard(client, admin_session):
    import uuid
    from tests.helpers import auth_headers, create_soldier

    soldier = create_soldier(
        admin_session,
        personal_number=f"cdash_regular_{uuid.uuid4().hex[:8]}",
        role="soldier",
    )
    admin_session.commit()

    response = client.get("/api/command-dashboard/summary", headers=auth_headers(soldier))

    assert response.status_code == 403


def test_admin_dashboard_scope_is_explicitly_all_top_level_nodes(client, admin_session):
    import uuid
    from tests.helpers import auth_headers, create_node, create_soldier

    first = create_node(admin_session, level="group", name=f"admin_first_{uuid.uuid4().hex[:8]}")
    second = create_node(admin_session, level="group", name=f"admin_second_{uuid.uuid4().hex[:8]}")
    first_soldier = create_soldier(
        admin_session,
        personal_number=f"cdash_admin_in_1_{uuid.uuid4().hex[:8]}",
        hierarchy_node_id=first.id,
    )
    second_soldier = create_soldier(
        admin_session,
        personal_number=f"cdash_admin_in_2_{uuid.uuid4().hex[:8]}",
        hierarchy_node_id=second.id,
    )
    admin = create_soldier(
        admin_session,
        personal_number=f"cdash_admin_{uuid.uuid4().hex[:8]}",
        role="admin",
    )
    admin_session.commit()

    response = client.get("/api/command-dashboard/soldiers", headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()}
    assert str(first_soldier.id) in ids
    assert str(second_soldier.id) in ids
