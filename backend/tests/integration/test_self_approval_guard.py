"""Regression tests: a commander/DM must not be able to approve or reject
their own submitted constraint or exemption request, even though their own
hierarchy node normally falls inside their own commanded/managed scope."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier

pytestmark = pytest.mark.duty


def test_commander_cannot_approve_own_constraint(client: TestClient, admin_session: Session):
    """A commander whose own node is inside their commanded scope cannot approve
    their own constraint request."""
    node = create_node(admin_session, level="group", name="Test Unit")
    commander = create_soldier(
        admin_session, personal_number="99001", role="commander", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    admin_session.commit()

    from app.db.models import PersonalConstraint

    c = PersonalConstraint(
        soldier_id=commander.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending_commander",
    )
    admin_session.add(c)
    admin_session.commit()

    resp = client.post(
        f"/api/constraints/{c.id}/approve",
        json={"decision_note": None},
        headers=auth_headers(commander),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "cannot_act_on_own_request"


def test_commander_cannot_reject_own_constraint(client: TestClient, admin_session: Session):
    """A commander cannot reject their own constraint request either."""
    node = create_node(admin_session, level="group", name="Test Unit")
    commander = create_soldier(
        admin_session, personal_number="99002", role="commander", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    admin_session.commit()

    from app.db.models import PersonalConstraint

    c = PersonalConstraint(
        soldier_id=commander.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending_commander",
    )
    admin_session.add(c)
    admin_session.commit()

    resp = client.post(
        f"/api/constraints/{c.id}/reject",
        json={"decision_note": "nope"},
        headers=auth_headers(commander),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "cannot_act_on_own_request"


def test_commander_can_approve_other_constraint(client: TestClient, admin_session: Session):
    """A commander CAN approve another soldier's constraint request (normal case)."""
    node = create_node(admin_session, level="group", name="Test Unit")
    commander = create_soldier(
        admin_session, personal_number="99003", role="commander", hierarchy_node_id=node.id
    )
    other_soldier = create_soldier(
        admin_session, personal_number="99004", role="soldier", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    admin_session.commit()

    from app.db.models import PersonalConstraint

    c = PersonalConstraint(
        soldier_id=other_soldier.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending_commander",
    )
    admin_session.add(c)
    admin_session.commit()

    resp = client.post(
        f"/api/constraints/{c.id}/approve",
        json={"decision_note": None},
        headers=auth_headers(commander),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_duty_manager"


def test_commander_cannot_approve_own_exemption_request(client: TestClient, admin_session: Session):
    """A commander cannot approve-commander their own exemption request."""
    node = create_node(admin_session, level="group", name="Test Unit")
    commander = create_soldier(
        admin_session, personal_number="99005", role="commander", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    admin_session.commit()

    from app.db.models import ExemptionRequest, ExemptionType

    # Create an exemption type first
    et = ExemptionType(name="test", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    req = ExemptionRequest(
        soldier_id=commander.id,
        exemption_type_id=et.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending_commander",
    )
    admin_session.add(req)
    admin_session.commit()

    resp = client.post(
        f"/api/exemption-requests/{req.id}/approve-commander",
        headers=auth_headers(commander),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "cannot_act_on_own_request"


def test_commander_cannot_reject_own_exemption_request(client: TestClient, admin_session: Session):
    """A commander cannot reject their own exemption request."""
    node = create_node(admin_session, level="group", name="Test Unit")
    commander = create_soldier(
        admin_session, personal_number="99006", role="commander", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    admin_session.commit()

    from app.db.models import ExemptionRequest, ExemptionType

    # Create an exemption type first
    et = ExemptionType(name="test", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    req = ExemptionRequest(
        soldier_id=commander.id,
        exemption_type_id=et.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending_commander",
    )
    admin_session.add(req)
    admin_session.commit()

    resp = client.post(
        f"/api/exemption-requests/{req.id}/reject",
        json={"decision_note": "nope"},
        headers=auth_headers(commander),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "cannot_act_on_own_request"


def test_duty_manager_cannot_approve_own_exemption_request(client: TestClient, admin_session: Session):
    """A duty manager cannot approve-duty-manager their own exemption request."""
    node = create_node(admin_session, level="group", name="Test Unit")
    duty_manager = create_soldier(
        admin_session, personal_number="99007", role="duty_manager", hierarchy_node_id=node.id
    )
    admin_session.commit()

    from app.db.models import ExemptionRequest, ExemptionType

    # Create an exemption type first
    et = ExemptionType(name="test", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    req = ExemptionRequest(
        soldier_id=duty_manager.id,
        exemption_type_id=et.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending_duty_manager",
    )
    admin_session.add(req)
    admin_session.commit()

    resp = client.post(
        f"/api/exemption-requests/{req.id}/approve-duty-manager",
        json={"decision_note": None},
        headers=auth_headers(duty_manager),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "cannot_act_on_own_request"
