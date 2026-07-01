from __future__ import annotations

import uuid
import pytest

from app.db.models import ExemptionRequest, HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _make_req(session, soldier, node):
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def _make_exemption(session, soldier, enrollment_req, status="pending"):
    from app.db.models import ExemptionType
    from datetime import date
    # find or create an exemption type
    from sqlalchemy import select
    et = session.execute(select(ExemptionType).limit(1)).scalar_one_or_none()
    if et is None:
        et = ExemptionType(name=f"type_{_uid()}", description=None)
        session.add(et)
        session.flush()
    ex = ExemptionRequest(
        soldier_id=soldier.id,
        exemption_type_id=et.id,
        start_date=date.today(),
        enrollment_request_id=enrollment_req.id,
        status=status,
    )
    session.add(ex)
    session.flush()
    return ex


def test_approve_without_exemptions_activates_immediately(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == node.id
    assert req.status == "approved"
    assert req.decided_by == decider.id


def test_approve_with_pending_exemptions_sets_commander_approved(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)
    _make_exemption(admin_session, soldier, req, status="pending")
    admin_session.commit()

    from app.services.enrollment import approve_enrollment
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert req.status == "commander_approved"
    assert soldier.hierarchy_node_id == holding.id


def test_try_activate_activates_when_all_exemptions_closed(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)
    # Manually set to commander_approved
    req.status = "commander_approved"
    ex = _make_exemption(admin_session, soldier, req, status="approved")
    admin_session.commit()

    from app.services.enrollment import try_activate
    try_activate(admin_session, req.id)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert req.status == "approved"
    assert soldier.hierarchy_node_id == node.id


def test_try_activate_does_not_activate_when_exemption_still_pending(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)
    req.status = "commander_approved"
    _make_exemption(admin_session, soldier, req, status="pending")
    admin_session.commit()

    from app.services.enrollment import try_activate
    try_activate(admin_session, req.id)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert req.status == "commander_approved"
    assert soldier.hierarchy_node_id == holding.id


def test_reject_leaves_soldier_in_holding(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import reject_enrollment
    reject_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note="not eligible")
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == holding.id
    assert req.status == "rejected"
    assert req.decision_note == "not eligible"


def test_approve_already_decided_raises(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment, EnrollmentError
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()

    with pytest.raises(EnrollmentError, match="already decided"):
        approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)


def test_list_pending_scoped_to_node_ids(admin_session):
    holding = _make_holding(admin_session)
    node_a = create_node(admin_session, level="unit", name=f"a_{_uid()}", parent=holding)
    node_b = create_node(admin_session, level="unit", name=f"b_{_uid()}", parent=holding)
    s1 = create_soldier(admin_session, personal_number=f"s1_{_uid()}", hierarchy_node_id=holding.id)
    s2 = create_soldier(admin_session, personal_number=f"s2_{_uid()}", hierarchy_node_id=holding.id)
    _make_req(admin_session, s1, node_a)
    _make_req(admin_session, s2, node_b)

    from app.services.enrollment import list_pending_for_node_ids
    results = list_pending_for_node_ids(admin_session, {node_a.id})
    assert len(results) == 1
    assert results[0].soldier_id == s1.id
