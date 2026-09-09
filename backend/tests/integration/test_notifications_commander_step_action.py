from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, ExemptionRequest, ExemptionType, PersonalConstraint
from app.services.action_tokens import create_token
from tests.helpers import auth_headers, create_node, create_soldier


def test_dispatch_constraint_approve_commander_step_rejects_in_scope_duty_manager(
    client: TestClient, admin_session: Session
):
    """Regression: the notifications '/api/action' quick-action dispatch used
    to call constraint_svc.approve_constraint directly with no authorization
    check, letting an in-scope-but-non-commanding duty manager approve the
    commander stage of a constraint. Approving the commander stage must be
    restricted to the actual commanding officer (or an admin)."""
    root = create_node(admin_session, level="department", name="na-cmdstep-root")
    target = create_soldier(admin_session, personal_number="na-cmdstep-target", hierarchy_node_id=root.id)
    duty_manager = create_soldier(admin_session, personal_number="na-cmdstep-dm", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=root.id))
    constraint = PersonalConstraint(
        soldier_id=target.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
        reason="regression", status="pending_commander",
    )
    admin_session.add(constraint)
    admin_session.commit()

    tok = create_token(
        admin_session, soldier_id=duty_manager.id, action="constraint:approve", resource_id=constraint.id,
    )
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(duty_manager), json={"token": tok})

    assert resp.status_code == 403, resp.text
    admin_session.expire_all()
    refreshed = admin_session.get(PersonalConstraint, constraint.id)
    assert refreshed.status == "pending_commander"


def test_dispatch_exemption_approve_commander_step_rejects_in_scope_duty_manager(
    client: TestClient, admin_session: Session
):
    """Same regression as the constraint case above, for exemption requests'
    commander-step approval dispatched via the notifications quick-action
    endpoint."""
    root = create_node(admin_session, level="department", name="na-exstep-root")
    target = create_soldier(admin_session, personal_number="na-exstep-target", hierarchy_node_id=root.id)
    duty_manager = create_soldier(admin_session, personal_number="na-exstep-dm", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=root.id))
    et = ExemptionType(name="na-exstep-type")
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=target.id, exemption_type_id=et.id, status="pending_commander",
        start_date=date(2026, 1, 1), reason="regression",
    )
    admin_session.add(req)
    admin_session.commit()

    tok = create_token(
        admin_session, soldier_id=duty_manager.id, action="exemption:approve", resource_id=req.id,
    )
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(duty_manager), json={"token": tok})

    assert resp.status_code == 403, resp.text
    admin_session.expire_all()
    refreshed = admin_session.get(ExemptionRequest, req.id)
    assert refreshed.status == "pending_commander"
