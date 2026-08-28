from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyLocation, DutyType, PersonalConstraint
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    """Create test infrastructure: node, duty manager, duty type, location."""
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt)
    session.add(loc)
    session.commit()
    return node, dm, dt, loc


def test_constrained_soldier_shows_warning_when_override_allowed(client, admin_session):
    """When override is allowed (default), a constrained soldier should have
    personal_constraint_warning set and blocked=False."""
    node, dm, dt, loc = _setup(admin_session, "sc_001")
    soldier = create_soldier(admin_session, personal_number="sc_001s", hierarchy_node_id=node.id)
    admin_session.commit()

    start_date = date(2026, 8, 1)
    end_date = date(2026, 8, 5)

    # Create shift
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "required_count": 1,
    }, headers=auth_headers(dm))
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    # Approve constraint for soldier during shift dates
    constraint = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=start_date,
        end_date=end_date,
        reason="חופשה",
        status="approved",
        decided_by=dm.id,
    )
    admin_session.add(constraint)
    admin_session.commit()

    # Get candidates
    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    assert resp.status_code == 200
    candidates = resp.json()

    # Find the constrained soldier
    row = next((c for c in candidates if c["soldier_id"] == str(soldier.id)), None)
    assert row is not None, "Constrained soldier should appear in candidates"

    # Verify: blocked should be False, personal_constraint_warning should be present
    assert row["blocked"] is False, "Constrained soldier should not be hard-blocked when override allowed"
    assert row["personal_constraint_warning"] is not None, "Warning should be present"
    assert row["personal_constraint_warning"]["reason"] == "חופשה"
    assert row["personal_constraint_warning"]["start_date"] == start_date.isoformat()
    assert row["personal_constraint_warning"]["end_date"] == end_date.isoformat()


def test_constrained_soldier_stays_blocked_when_override_disallowed(client, admin_session):
    """When override is disabled, a constrained soldier should stay blocked
    and personal_constraint_warning should be None."""
    node, dm, dt, loc = _setup(admin_session, "sc_002")
    soldier = create_soldier(admin_session, personal_number="sc_002s", hierarchy_node_id=node.id)
    admin_session.commit()

    start_date = date(2026, 8, 1)
    end_date = date(2026, 8, 5)

    # Disable override
    set_setting(admin_session, "constraints.allow_manual_override", False, actor_id=None)
    admin_session.commit()

    # Create shift
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "required_count": 1,
    }, headers=auth_headers(dm))
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    # Approve constraint for soldier during shift dates
    constraint = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=start_date,
        end_date=end_date,
        reason="חופשה",
        status="approved",
        decided_by=dm.id,
    )
    admin_session.add(constraint)
    admin_session.commit()

    # Get candidates
    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    assert resp.status_code == 200
    candidates = resp.json()

    # Find the constrained soldier
    row = next((c for c in candidates if c["soldier_id"] == str(soldier.id)), None)
    assert row is not None, "Constrained soldier should appear in candidates"

    # Verify: blocked should be True, personal_constraint_warning should be None
    assert row["blocked"] is True, "Constrained soldier should be hard-blocked when override disabled"
    assert row["blocked_reason"] == "constraint"
    assert row.get("personal_constraint_warning") is None, "Warning should not be present when override disabled"


def test_constrained_candidates_sort_last(client, admin_session):
    """Constrained-but-selectable candidates should sort after unconstrained ones
    but before hard-blocked ones."""
    node, dm, dt, loc = _setup(admin_session, "sc_003")
    unconstrained = create_soldier(admin_session, personal_number="sc_003u", hierarchy_node_id=node.id)
    constrained = create_soldier(admin_session, personal_number="sc_003c", hierarchy_node_id=node.id)
    admin_session.commit()

    start_date = date(2026, 8, 1)
    end_date = date(2026, 8, 5)

    # Create shift
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "required_count": 1,
    }, headers=auth_headers(dm))
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    # Approve constraint for constrained soldier
    constraint = PersonalConstraint(
        soldier_id=constrained.id,
        start_date=start_date,
        end_date=end_date,
        reason="חופשה",
        status="approved",
        decided_by=dm.id,
    )
    admin_session.add(constraint)
    admin_session.commit()

    # Get candidates
    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    assert resp.status_code == 200
    candidates = resp.json()

    # Extract IDs in order
    ids = [c["soldier_id"] for c in candidates]

    # Constrained should appear after unconstrained (but both should be present)
    constrained_idx = ids.index(str(constrained.id))
    unconstrained_idx = ids.index(str(unconstrained.id))
    assert constrained_idx > unconstrained_idx, \
        "Constrained soldier should sort after unconstrained soldier"
