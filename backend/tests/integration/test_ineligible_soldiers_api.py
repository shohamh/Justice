from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.db.models import (
    DutyAssignment,
    DutyManagerScope,
    DutyType,
    RangeAssignment,
    RangeEvent,
    RangeType,
)
from app.services.settings_loader import set_setting
from tests.helpers import (
    auth_headers,
    create_duty_location,
    create_node,
    create_range_location,
    create_soldier,
)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _list(client, soldier, audience: str):
    return client.get(
        f"/api/ranges/ineligible-soldiers?audience={audience}",
        headers=auth_headers(soldier),
    )


def _add_future_weapon_duty_and_matching_range(session, *, soldier, node) -> None:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)
    duty_location = create_duty_location(session, name=f"duty-location-{_uid()}")
    range_location = create_range_location(session, name=f"range-location-{_uid()}")
    duty_type = DutyType(
        name=f"weapon-duty-{_uid()}",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        required_range_type=RangeType.laser,
    )
    session.add(duty_type)
    session.flush()
    session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=duty_location.id,
            start_date=date.today() + timedelta(days=7),
            end_date=date.today() + timedelta(days=7),
            status="published",
        )
    )
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        date=date.today() + timedelta(days=3),
        range_location_id=range_location.id,
        required_count=1,
    )
    session.add(event)
    session.flush()
    session.add(RangeAssignment(range_event_id=event.id, soldier_id=soldier.id))
    session.commit()


def test_commander_view_includes_descendants_and_excludes_duty_manager_only_nodes(
    client, admin_session
) -> None:
    commander = create_soldier(
        admin_session, personal_number=f"commander-{_uid()}", role="commander"
    )
    commanded_root = create_node(
        admin_session,
        level="division",
        name=f"commanded-root-{_uid()}",
        commander_id=commander.id,
    )
    commanded_child = create_node(
        admin_session,
        level="unit",
        name=f"commanded-child-{_uid()}",
        parent=commanded_root,
    )
    duty_manager_root = create_node(
        admin_session, level="division", name=f"duty-manager-root-{_uid()}"
    )
    root_soldier = create_soldier(
        admin_session,
        personal_number=f"command-root-{_uid()}",
        hierarchy_node_id=commanded_root.id,
    )
    descendant_soldier = create_soldier(
        admin_session,
        personal_number=f"command-child-{_uid()}",
        hierarchy_node_id=commanded_child.id,
    )
    excluded_soldier = create_soldier(
        admin_session,
        personal_number=f"duty-only-{_uid()}",
        hierarchy_node_id=duty_manager_root.id,
    )
    _add_future_weapon_duty_and_matching_range(
        admin_session, soldier=descendant_soldier, node=commanded_child
    )

    response = _list(client, commander, "commander")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert {soldier["soldier_id"] for soldier in body["soldiers"]} == {
        str(root_soldier.id),
        str(descendant_soldier.id),
    }
    assert str(excluded_soldier.id) not in {soldier["soldier_id"] for soldier in body["soldiers"]}
    assert {node["id"] for node in body["nodes"]} == {
        str(commanded_root.id),
        str(commanded_child.id),
    }
    descendant = next(
        soldier
        for soldier in body["soldiers"]
        if soldier["soldier_id"] == str(descendant_soldier.id)
    )
    assert descendant["hierarchy_path_ids"] == [
        str(commanded_root.id),
        str(commanded_child.id),
    ]
    assert descendant["valid_qualifications"] == []
    assert descendant["has_upcoming_weapon_duty"] is True
    assert descendant["has_upcoming_matching_range"] is True
    assert descendant["upcoming_weapon_duties"][0]["eligible"] is True
    assert descendant["upcoming_weapon_duties"][0]["qualification_source"] == "planned_range"
    assert (
        descendant["upcoming_weapon_duties"][0]["covered_by_range_date"]
        == (date.today() + timedelta(days=3)).isoformat()
    )
    assert (
        descendant["upcoming_weapon_duties"][0]["start_date"]
        == (date.today() + timedelta(days=7)).isoformat()
    )
    assert (
        descendant["upcoming_matching_ranges"][0]["date"]
        == (date.today() + timedelta(days=3)).isoformat()
    )


def test_planning_view_combines_all_duty_manager_roots_and_deduplicates_overlap(
    client, admin_session
) -> None:
    planning_root = create_node(admin_session, level="division", name=f"planning-root-{_uid()}")
    planning_child = create_node(
        admin_session, level="unit", name=f"planning-child-{_uid()}", parent=planning_root
    )
    second_planning_root = create_node(
        admin_session, level="division", name=f"planning-second-{_uid()}"
    )
    out_of_scope_root = create_node(admin_session, level="division", name=f"planning-out-{_uid()}")
    duty_manager = create_soldier(
        admin_session,
        personal_number=f"planner-{_uid()}",
        role="duty_manager",
    )
    admin_session.add_all(
        [
            DutyManagerScope(
                duty_manager_id=duty_manager.id,
                hierarchy_node_id=planning_root.id,
            ),
            DutyManagerScope(
                duty_manager_id=duty_manager.id,
                hierarchy_node_id=planning_child.id,
            ),
            DutyManagerScope(
                duty_manager_id=duty_manager.id,
                hierarchy_node_id=second_planning_root.id,
            ),
        ]
    )
    root_soldier = create_soldier(
        admin_session,
        personal_number=f"planning-root-{_uid()}",
        hierarchy_node_id=planning_root.id,
    )
    overlapping_soldier = create_soldier(
        admin_session,
        personal_number=f"planning-overlap-{_uid()}",
        hierarchy_node_id=planning_child.id,
    )
    second_soldier = create_soldier(
        admin_session,
        personal_number=f"planning-second-{_uid()}",
        hierarchy_node_id=second_planning_root.id,
    )
    excluded_soldier = create_soldier(
        admin_session,
        personal_number=f"planning-out-{_uid()}",
        hierarchy_node_id=out_of_scope_root.id,
    )
    admin_session.commit()

    response = _list(client, duty_manager, "planning")

    assert response.status_code == 200, response.text
    body = response.json()
    soldier_ids = [soldier["soldier_id"] for soldier in body["soldiers"]]
    assert body["count"] == 3
    assert set(soldier_ids) == {
        str(root_soldier.id),
        str(overlapping_soldier.id),
        str(second_soldier.id),
    }
    assert soldier_ids.count(str(overlapping_soldier.id)) == 1
    assert str(excluded_soldier.id) not in soldier_ids
    nodes_by_id = {node["id"]: node for node in body["nodes"]}
    assert nodes_by_id[str(planning_root.id)]["path_ids"] == [str(planning_root.id)]
    assert nodes_by_id[str(planning_root.id)]["parent_id"] is None
    assert nodes_by_id[str(planning_child.id)]["path_ids"] == [
        str(planning_root.id),
        str(planning_child.id),
    ]
    assert nodes_by_id[str(planning_child.id)]["parent_id"] == str(planning_root.id)
    assert nodes_by_id[str(second_planning_root.id)]["path_ids"] == [str(second_planning_root.id)]
    assert nodes_by_id[str(second_planning_root.id)]["parent_id"] is None
    soldiers_by_id = {soldier["soldier_id"]: soldier for soldier in body["soldiers"]}
    assert soldiers_by_id[str(root_soldier.id)]["hierarchy_path_ids"] == [str(planning_root.id)]
    assert soldiers_by_id[str(overlapping_soldier.id)]["hierarchy_path_ids"] == [
        str(planning_root.id),
        str(planning_child.id),
    ]
    assert soldiers_by_id[str(second_soldier.id)]["hierarchy_path_ids"] == [
        str(second_planning_root.id)
    ]

    count_response = client.get(
        "/api/ranges/ineligible-soldiers/count", headers=auth_headers(duty_manager)
    )
    assert count_response.status_code == 200, count_response.text
    assert count_response.json() == {"count": len(set(soldier_ids))}


def test_admin_sees_all_nodes_and_count_matches_planning_list(client, admin_session) -> None:
    first_node = create_node(admin_session, level="division", name=f"admin-first-{_uid()}")
    second_node = create_node(admin_session, level="division", name=f"admin-second-{_uid()}")
    first_soldier = create_soldier(
        admin_session, personal_number=f"admin-first-{_uid()}", hierarchy_node_id=first_node.id
    )
    second_soldier = create_soldier(
        admin_session, personal_number=f"admin-second-{_uid()}", hierarchy_node_id=second_node.id
    )
    admin = create_soldier(admin_session, personal_number=f"admin-{_uid()}", role="admin")

    commander_response = _list(client, admin, "commander")
    planning_response = _list(client, admin, "planning")
    count_response = client.get(
        "/api/ranges/ineligible-soldiers/count", headers=auth_headers(admin)
    )

    assert commander_response.status_code == 200, commander_response.text
    assert planning_response.status_code == 200, planning_response.text
    assert count_response.status_code == 200, count_response.text
    expected_ids = {str(first_soldier.id), str(second_soldier.id)}
    assert {
        soldier["soldier_id"] for soldier in commander_response.json()["soldiers"]
    } == expected_ids
    planning_body = planning_response.json()
    assert {soldier["soldier_id"] for soldier in planning_body["soldiers"]} == expected_ids
    assert count_response.json() == {"count": len(planning_body["soldiers"])}


def test_rejects_users_without_the_requested_audience_authority(client, admin_session) -> None:
    commander = create_soldier(
        admin_session, personal_number=f"forbidden-commander-{_uid()}", role="commander"
    )
    commander_node = create_node(
        admin_session,
        level="division",
        name=f"forbidden-command-{_uid()}",
        commander_id=commander.id,
    )
    duty_manager = create_soldier(
        admin_session,
        personal_number=f"forbidden-planner-{_uid()}",
        role="duty_manager",
        hierarchy_node_id=commander_node.id,
    )
    soldier = create_soldier(admin_session, personal_number=f"forbidden-soldier-{_uid()}")

    assert _list(client, commander, "planning").status_code == 403
    assert _list(client, duty_manager, "commander").status_code == 403
    assert _list(client, soldier, "planning").status_code == 403
    assert _list(client, soldier, "commander").status_code == 403


def test_planning_scope_with_no_soldiers_returns_an_empty_list_and_zero_count(
    client, admin_session
) -> None:
    empty_root = create_node(admin_session, level="division", name=f"empty-root-{_uid()}")
    duty_manager = create_soldier(
        admin_session, personal_number=f"empty-planner-{_uid()}", role="duty_manager"
    )
    admin_session.add(
        DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=empty_root.id)
    )
    admin_session.commit()

    list_response = _list(client, duty_manager, "planning")
    count_response = client.get(
        "/api/ranges/ineligible-soldiers/count", headers=auth_headers(duty_manager)
    )

    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == {"count": 0, "nodes": [], "soldiers": []}
    assert count_response.status_code == 200, count_response.text
    assert count_response.json() == {"count": 0}


def test_nested_scope_roots_do_not_expose_ancestor_metadata(client, admin_session) -> None:
    ancestor = create_node(admin_session, level="division", name=f"ancestor-{_uid()}")
    commander = create_soldier(
        admin_session, personal_number=f"nested-commander-{_uid()}", role="commander"
    )
    commander_root = create_node(
        admin_session,
        level="unit",
        name=f"commander-root-{_uid()}",
        parent=ancestor,
        commander_id=commander.id,
    )
    commander_child = create_node(
        admin_session,
        level="team",
        name=f"commander-child-{_uid()}",
        parent=commander_root,
    )
    commander_soldier = create_soldier(
        admin_session,
        personal_number=f"commander-scoped-{_uid()}",
        hierarchy_node_id=commander_child.id,
    )
    duty_manager = create_soldier(
        admin_session,
        personal_number=f"nested-planner-{_uid()}",
        role="duty_manager",
    )
    planning_root = create_node(
        admin_session,
        level="unit",
        name=f"planning-root-{_uid()}",
        parent=ancestor,
    )
    planning_child = create_node(
        admin_session,
        level="team",
        name=f"planning-child-{_uid()}",
        parent=planning_root,
    )
    planning_soldier = create_soldier(
        admin_session,
        personal_number=f"planning-scoped-{_uid()}",
        hierarchy_node_id=planning_child.id,
    )
    admin_session.add(
        DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=planning_root.id)
    )
    admin_session.commit()

    responses = [
        (_list(client, commander, "commander"), commander_root, commander_child, commander_soldier),
        (_list(client, duty_manager, "planning"), planning_root, planning_child, planning_soldier),
    ]

    for response, root, child, soldier in responses:
        assert response.status_code == 200, response.text
        assert str(ancestor.id) not in response.text
        body = response.json()
        assert {node["id"] for node in body["nodes"]} == {str(root.id), str(child.id)}
        root_node = next(node for node in body["nodes"] if node["id"] == str(root.id))
        assert root_node["parent_id"] is None
        assert root_node["path_ids"] == [str(root.id)]
        soldier_row = next(row for row in body["soldiers"] if row["soldier_id"] == str(soldier.id))
        assert soldier_row["hierarchy_path_ids"] == [str(root.id), str(child.id)]
