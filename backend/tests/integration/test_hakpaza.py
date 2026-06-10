from __future__ import annotations

from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn_prefix: str):
    node = create_node(session, level="branch", name=f"n_{pn_prefix}")
    dm = create_soldier(session, personal_number=f"{pn_prefix}_dm", role="duty_manager", hierarchy_node_id=node.id)
    commander = create_soldier(session, personal_number=f"{pn_prefix}_cmd", role="commander", hierarchy_node_id=node.id)
    pulled = create_soldier(session, personal_number=f"{pn_prefix}_p", role="soldier", hierarchy_node_id=node.id)
    replacement = create_soldier(session, personal_number=f"{pn_prefix}_r", role="soldier", hierarchy_node_id=node.id)

    dt = DutyType(name=f"dt_{pn_prefix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{pn_prefix}")
    session.add(dt)
    session.add(loc)
    session.flush()

    assignment = DutyAssignment(
        soldier_id=pulled.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2030-01-01",
        end_date="2030-01-10",
        status="published",
        is_reserve=False,
    )
    session.add(assignment)
    session.commit()

    return dm, commander, pulled, replacement, assignment


def test_create_hakpaza(client, admin_session):
    dm, commander, pulled, replacement, assignment = _setup(admin_session, "hk001")

    resp = client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(assignment.id),
            "pull_date": "2030-01-05",
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["pulled_soldier_id"] == str(pulled.id)
    assert data["replacement_soldier_id"] == str(replacement.id)


def test_approve_hakpaza_splits_assignment(client, admin_session):
    dm, commander, pulled, replacement, assignment = _setup(admin_session, "hk002")

    create_resp = client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(assignment.id),
            "pull_date": "2030-01-05",
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )
    assert create_resp.status_code == 201
    hakpaza_id = create_resp.json()["id"]

    approve_resp = client.post(
        f"/api/hakpaza/{hakpaza_id}/approve",
        headers=auth_headers(dm),
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["status"] == "approved"
    assert data["replacement_assignment_id"] is not None


def test_reject_hakpaza(client, admin_session):
    dm, commander, pulled, replacement, assignment = _setup(admin_session, "hk003")

    create_resp = client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(assignment.id),
            "pull_date": "2030-01-05",
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )
    assert create_resp.status_code == 201
    hakpaza_id = create_resp.json()["id"]

    reject_resp = client.post(
        f"/api/hakpaza/{hakpaza_id}/reject",
        headers=auth_headers(dm),
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"


def test_pending_count(client, admin_session):
    dm, commander, pulled, replacement, assignment = _setup(admin_session, "hk004")

    client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(assignment.id),
            "pull_date": "2030-01-05",
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )

    resp = client.get("/api/hakpaza/pending-count", headers=auth_headers(dm))
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


def test_approve_hakpaza_sets_multiplier_no_score_adjustment(client, admin_session):
    """Approving a hakpaza sets forced_call_up_multiplier on the replacement
    assignment and does NOT create a ScoreAdjustment."""
    from app.db.models import ScoreAdjustment
    from sqlalchemy import select

    dm, commander, pulled, replacement, assignment = _setup(admin_session, "hk005")

    create_resp = client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(assignment.id),
            "pull_date": "2030-01-05",
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )
    assert create_resp.status_code == 201
    hakpaza_id = create_resp.json()["id"]

    approve_resp = client.post(
        f"/api/hakpaza/{hakpaza_id}/approve",
        headers=auth_headers(dm),
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["replacement_assignment_id"] is not None

    # replacement assignment must have the multiplier set
    from app.db.models import DutyAssignment
    repl_asgn = admin_session.get(DutyAssignment, data["replacement_assignment_id"])
    assert repl_asgn is not None
    assert repl_asgn.forced_call_up_multiplier == Decimal("2.0")

    # no ScoreAdjustment should have been created for the replacement soldier
    adjs = admin_session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == replacement.id)
    ).scalars().all()
    assert adjs == []
