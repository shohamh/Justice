from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyManagerScope,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    ForcedCallup,
    HierarchyTransferRequest,
    PersonalConstraint,
    SoldierEnrollmentRequest,
    SoldierFieldUpdate,
    SwapCandidate,
    SwapRequest,
)
from app.services import nav_counts as nav_counts_service
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _id() -> str:
    return uuid.uuid4().hex[:10]


def _build_badge_dataset(session: Session) -> dict[str, object]:
    suffix = _id()
    admin = create_soldier(session, personal_number=f"nav_admin_{suffix}", role="admin")
    commander = create_soldier(session, personal_number=f"nav_cmd_{suffix}", role="commander")
    duty_manager = create_soldier(session, personal_number=f"nav_dm_{suffix}", role="duty_manager")
    dual_role = create_soldier(session, personal_number=f"nav_dual_{suffix}", role="commander")
    no_scope = create_soldier(session, personal_number=f"nav_none_{suffix}", role="commander")

    group = create_node(session, level="group", name=f"nav-group-{suffix}", commander_id=commander.id)
    branch = create_node(session, level="branch", name=f"nav-branch-{suffix}", parent=group, commander_id=dual_role.id)
    session.add_all([
        DutyManagerScope(duty_manager_id=admin.id, hierarchy_node_id=branch.id),
        DutyManagerScope(duty_manager_id=dual_role.id, hierarchy_node_id=branch.id),
    ])
    duty_manager.hierarchy_node_id = branch.id
    target = create_soldier(session, personal_number=f"nav_target_{suffix}", hierarchy_node_id=branch.id)

    session.add(PersonalConstraint(
        soldier_id=target.id,
        start_date=date.today() + timedelta(days=10),
        end_date=date.today() + timedelta(days=12),
        reason="badge parity",
        status="pending_commander",
    ))

    exemption_type = ExemptionType(name=f"nav-exemption-{suffix}", is_commander_exemption=False)
    session.add(exemption_type)
    session.flush()
    session.add_all([
        ExemptionRequest(
            soldier_id=target.id,
            exemption_type_id=exemption_type.id,
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=12),
            reason="commander step",
            status="pending_commander",
        ),
        ExemptionRequest(
            soldier_id=target.id,
            exemption_type_id=exemption_type.id,
            start_date=date.today() + timedelta(days=13),
            end_date=date.today() + timedelta(days=15),
            reason="duty manager step",
            status="pending_duty_manager",
        ),
    ])
    session.add_all([
        SoldierFieldUpdate(
            soldier_id=target.id, field_name="unit_join_date", new_value="2026-01-01",
            status="pending_commander",
        ),
        SoldierFieldUpdate(
            soldier_id=target.id, field_name="military_driving_license", new_value="yes",
            status="pending_duty_manager",
        ),
    ])
    session.add(SoldierEnrollmentRequest(
        soldier_id=target.id, requested_node_id=branch.id, status="pending",
    ))
    session.add(HierarchyTransferRequest(
        soldier_id=target.id, requested_by=target.id, from_node_id=branch.id,
        to_node_id=branch.id, status="pending",
    ))

    duty_type = DutyType(name=f"nav-duty-{suffix}", score_per_day=1)
    duty_location = DutyLocation(name=f"nav-location-{suffix}")
    session.add_all([duty_type, duty_location])
    session.flush()
    for index, actor in enumerate((admin, commander, duty_manager, dual_role, no_scope)):
        assignment = DutyAssignment(
            duty_type_id=duty_type.id,
            duty_location_id=duty_location.id,
            soldier_id=target.id,
            start_date=date.today() + timedelta(days=20 + index),
            end_date=date.today() + timedelta(days=21 + index),
            status="published",
        )
        session.add(assignment)
        session.flush()
        request = SwapRequest(
            duty_assignment_id=assignment.id,
            duty_date=assignment.start_date,
            requesting_soldier_id=target.id,
            status="open",
            open_to_marketplace=False,
        )
        session.add(request)
        session.flush()
        session.add(SwapCandidate(
            swap_request_id=request.id,
            soldier_id=actor.id,
            source="invited",
            status="pending",
        ))

    set_setting(session, "forced_callup.enabled", True, actor_id=None)
    session.add(ForcedCallup(
        initiator_id=admin.id,
        pulled_soldier_id=target.id,
        original_assignment_id=uuid.uuid4(),
        pull_date=date.today() + timedelta(days=30),
        replacement_soldier_id=commander.id,
        status="pending",
    ))
    session.commit()
    return {
        "admin": admin,
        "commander": commander,
        "duty_manager": duty_manager,
        "dual_role": dual_role,
        "no_scope": no_scope,
    }


def _legacy_nav_counts(client: TestClient, actor) -> dict[str, int]:
    headers = auth_headers(actor)

    def count_endpoint(path: str) -> int:
        response = client.get(path, headers=headers)
        if response.status_code == 403:
            return 0  # UnifiedNav independently catches this source and shows zero.
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        return response.json()["count"]

    constraints = count_endpoint("/api/constraints/pending/count")
    exemptions = count_endpoint("/api/exemption-requests/pending/count")
    field_updates = count_endpoint("/api/soldiers/field-updates/pending/count")

    enrollments_response = client.get("/api/enrollment-requests/pending", headers=headers)
    assert enrollments_response.status_code == 200, enrollments_response.text
    enrollments = len(enrollments_response.json())

    swaps_response = client.get("/api/swaps/pending", headers=headers)
    if swaps_response.status_code == 403:
        actionable_swaps = 0
    else:
        assert swaps_response.status_code == 200, swaps_response.text
        swaps = swaps_response.json()
        if actor.role == "admin":
            actionable_swaps = len(swaps)
        else:
            actor_id = str(actor.id)
            actionable_swaps = sum(
                actor_id in {approval["commander_id"] for approval in row["requester_manager_approvals"]}
                or any(
                    candidate["status"] in {"pending", "accepted"}
                    and actor_id in {approval["commander_id"] for approval in candidate["manager_approvals"]}
                    for candidate in row["candidates"]
                )
                for row in swaps
            )

    transfers_response = client.get("/api/hierarchy-transfers/pending", headers=headers)
    assert transfers_response.status_code == 200, transfers_response.text
    transfers = len(transfers_response.json())
    hakpaza = count_endpoint("/api/hakpaza/pending-count")
    incoming_swaps = count_endpoint("/api/swaps/incoming/count")
    return {
        "approvals": constraints + exemptions + field_updates + enrollments + actionable_swaps + transfers,
        "hakpaza": hakpaza,
        "incoming_swaps": incoming_swaps,
    }


@pytest.mark.parametrize("actor_key", ["admin", "commander", "duty_manager", "dual_role", "no_scope"])
def test_nav_count_endpoint_matches_existing_badge_contracts_for_role_scopes(
    client: TestClient,
    admin_session: Session,
    actor_key: str,
):
    actors = _build_badge_dataset(admin_session)
    actor = actors[actor_key]
    expected = _legacy_nav_counts(client, actor)

    response = client.get("/api/nav/counts", headers=auth_headers(actor))

    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert expected["incoming_swaps"] == 1
    if actor_key in {"no_scope", "duty_manager"}:
        assert expected["approvals"] == 0
    else:
        assert expected["approvals"] > 0


def test_nav_count_source_failure_does_not_zero_other_badges(
    client: TestClient,
    admin_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    admin = create_soldier(admin_session, personal_number=f"nav_failure_{_id()}", role="admin")

    def fail_constraint_count(_session: Session, _actor) -> int:
        raise RuntimeError("injected count-source failure")

    monkeypatch.setattr(nav_counts_service, "_count_constraints", fail_constraint_count)
    monkeypatch.setattr(nav_counts_service, "_count_exemptions", lambda *_: 2)
    monkeypatch.setattr(nav_counts_service, "_count_field_updates", lambda *_: 3)
    monkeypatch.setattr(nav_counts_service, "_count_enrollments", lambda *_: 4)
    monkeypatch.setattr(nav_counts_service, "_count_actionable_swaps", lambda *_: 5)
    monkeypatch.setattr(nav_counts_service.hierarchy_transfers, "list_pending_for_approver", lambda **_: [])
    monkeypatch.setattr(nav_counts_service, "_count_hakpaza", lambda *_: 6)
    monkeypatch.setattr(nav_counts_service, "_count_incoming_swaps", lambda *_: 7)

    response = client.get("/api/nav/counts", headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    assert response.json() == {"approvals": 14, "hakpaza": 6, "incoming_swaps": 7}


def test_admin_constraint_badge_counts_pending_rows_except_own_with_sql_count(
    client: TestClient,
    admin_session: Session,
):
    from sqlalchemy import event

    admin = create_soldier(admin_session, personal_number=f"nav_admin_constraint_{_id()}", role="admin")
    target = create_soldier(admin_session, personal_number=f"nav_constraint_target_{_id()}")
    admin_session.add_all([
        PersonalConstraint(
            soldier_id=target.id,
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=11),
            reason="admin can approve",
            status="pending_commander",
        ),
        PersonalConstraint(
            soldier_id=admin.id,
            start_date=date.today() + timedelta(days=12),
            end_date=date.today() + timedelta(days=13),
            reason="own request is excluded",
            status="pending_duty_manager",
        ),
    ])
    admin_session.commit()
    expected = client.get("/api/constraints/pending/count", headers=auth_headers(admin))
    assert expected.status_code == 200, expected.text
    statements: list[str] = []
    bind = admin_session.get_bind()

    def capture(_conn, _cursor, statement, *_):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        actual = nav_counts_service._count_constraints(admin_session, admin)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert actual == expected.json()["count"] == 1
    constraint_queries = [sql.lower() for sql in statements if "personal_constraints" in sql.lower()]
    assert any("count(" in sql for sql in constraint_queries)
    assert not any("select personal_constraints." in sql for sql in constraint_queries)
    assert any(
        "soldier_id" in sql and ("!=" in sql or "<>" in sql)
        for sql in constraint_queries
    )
