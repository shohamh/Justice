from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.db.models import (
    DutyManagerScope,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    SoldierExemption,
    SystemSetting,
)
from tests.helpers import auth_headers, create_node, create_soldier


def _revision(session, table: str) -> int:
    return session.execute(text(f"SELECT revision FROM {table} WHERE singleton = TRUE")).scalar_one()


def test_roster_revision_tracks_all_roster_tree_and_hakpaza_fields(admin_session):
    manager = create_soldier(admin_session, personal_number="cursor-rev-dm", role="soldier")
    commander = create_soldier(admin_session, personal_number="cursor-rev-cmd")
    parent = create_node(admin_session, level="department", name="cursor-rev-parent")
    node = create_node(admin_session, level="team", name="cursor-rev-node")
    duty_type = DutyType(name="cursor-rev-duty", score_per_day=Decimal("1"))
    admin_session.add(duty_type)
    admin_session.commit()

    revision = _revision(admin_session, "soldier_roster_revision")

    admin_session.execute(
        text("UPDATE soldiers SET rank = 'captain' WHERE id = :id"), {"id": manager.id}
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE hierarchy_nodes SET level = 'branch' WHERE id = :id"), {"id": node.id}
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE hierarchy_nodes SET commander_id = :commander WHERE id = :id"),
        {"id": node.id, "commander": commander.id},
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE hierarchy_nodes SET parent_id = :parent WHERE id = :id"),
        {"id": node.id, "parent": parent.id},
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.add(DutyManagerScope(duty_manager_id=manager.id, hierarchy_node_id=node.id))
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE duty_types SET name = 'cursor-rev-duty-renamed' WHERE id = :id"),
        {"id": duty_type.id},
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1


def test_transparency_page_cursor_rejects_fairness_membership_change(
    client, admin_session, monkeypatch
):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="cursor-rev-admin", role="admin")
    first_soldier = create_soldier(admin_session, personal_number="cursor-rev-first")
    second_soldier = create_soldier(admin_session, personal_number="cursor-rev-second")
    first_id = first_soldier.id
    second_id = second_soldier.id
    duty_type = DutyType(name="cursor-rev-fairness-duty", score_per_day=Decimal("1"))
    exemption_type = ExemptionType(name="cursor-rev-fairness-exemption")
    admin_session.add_all([duty_type, exemption_type])
    admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=second_id,
            exemption_type_id=exemption_type.id,
            start_date=date.today(),
        )
    )
    admin_session.commit()

    def row(soldier_id: uuid.UUID, name: str, burden_share: float) -> dict:
        return {
            "soldier_id": soldier_id,
            "full_name": name,
            "node_id": None,
            "node_name": None,
            "enrolled_at": date(2020, 1, 1),
            "active_days": 10,
            "shift_count": 1,
            "rank": None,
            "is_officer": False,
            "service_type": None,
            "cumulative_score": Decimal("2.00"),
            "score_per_day": Decimal("0.20"),
            "normalised_score": Decimal("1.00"),
            "is_globally_exempted": False,
            "burden_share": burden_share,
            "c_over_d": 1.0,
            "burden_share_offset_raw": 0,
            "exemptions_display": "",
            "exemptions_visible": False,
            "exemptions": [],
            "has_global_exemption": None,
            "has_partial_exemption": None,
            "has_temporary_exemption": None,
        }

    source_rows = [row(first_id, "First", 0.9), row(second_id, "Second", 0.2)]
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(item) for item in source_rows],
            "can_see_exemption_aggregates": True,
        },
    )
    def fairness_components(session, *, viewer, node_id):
        mapping_exists = (
            session.query(ExemptionDutyTypeMap)
            .filter_by(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
            .count()
            > 0
        )
        members = [str(first_id)] if mapping_exists else [str(first_id), str(second_id)]
        exempt = [str(second_id)] if mapping_exists else []
        return {
            "components": [{"soldiers": [{"soldier_id": soldier_id} for soldier_id in members]}],
            "exempt_from_all": {"soldiers": [{"soldier_id": soldier_id} for soldier_id in exempt]},
        }

    monkeypatch.setattr(scoring_route.svc, "fairness_components", fairness_components)

    first_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0"},
        headers=auth_headers(admin),
    )
    assert first_page.status_code == 200
    cursor = first_page.json()["next_cursor"]
    assert cursor

    admin_session.add(
        ExemptionDutyTypeMap(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
    )
    admin_session.commit()

    second_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0", "cursor": cursor},
        headers=auth_headers(admin),
    )
    assert second_page.status_code == 409
    assert second_page.json()["detail"] == "stale_cursor"


def test_transparency_page_rejects_scope_change_during_page_assembly(
    client, admin_session, monkeypatch
):
    from app.routes import scoring as scoring_route

    node = create_node(admin_session, level="department", name="cursor-race-scoped")
    added_node = create_node(admin_session, level="department", name="cursor-race-added")
    manager = create_soldier(
        admin_session,
        personal_number="cursor-race-manager",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    target = create_soldier(admin_session, personal_number="cursor-race-target")
    source_row = {
        "soldier_id": target.id,
        "full_name": "Target",
        "node_id": node.id,
        "node_name": node.name,
        "enrolled_at": date(2020, 1, 1),
        "active_days": 10,
        "shift_count": 1,
        "rank": None,
        "is_officer": False,
        "service_type": None,
        "cumulative_score": Decimal("2.00"),
        "score_per_day": Decimal("0.20"),
        "normalised_score": Decimal("1.00"),
        "is_globally_exempted": False,
        "burden_share": 0.5,
        "c_over_d": 1.0,
        "burden_share_offset_raw": 0,
        "exemptions_display": "",
        "exemptions_visible": False,
        "exemptions": [],
        "has_global_exemption": None,
        "has_partial_exemption": None,
        "has_temporary_exemption": None,
    }
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(source_row)],
            "can_see_exemption_aggregates": True,
        },
    )

    def mutate_scope_during_grouping(session, *, viewer, node_id):
        session.add(
            DutyManagerScope(duty_manager_id=manager.id, hierarchy_node_id=added_node.id)
        )
        session.flush()
        return {
            "components": [{"soldiers": [{"soldier_id": str(target.id)}]}],
            "exempt_from_all": {"soldiers": []},
        }

    monkeypatch.setattr(scoring_route.svc, "fairness_components", mutate_scope_during_grouping)

    response = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0"},
        headers=auth_headers(manager),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "data_changed"


def test_transparency_fairness_revision_tracks_eligibility_and_scope_mutations(admin_session):
    soldier = create_soldier(admin_session, personal_number="cursor-rev-eligibility")
    duty_type = DutyType(name="cursor-rev-eligibility-duty", score_per_day=Decimal("1"))
    exemption_type = ExemptionType(name="cursor-rev-eligibility-exemption")
    admin_session.add_all([duty_type, exemption_type])
    admin_session.commit()

    revision = _revision(admin_session, "transparency_fairness_revision")

    duty_type.active = False
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    duty_type.requirements = {"allowed_genders": ["female"]}
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    exemption_type.is_global = True
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    admin_session.add(
        ExemptionDutyTypeMap(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
    )
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE soldiers SET gender = 'female' WHERE id = :id"), {"id": soldier.id}
    )
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    today = date.today()
    admin_session.add(
        SoldierExemption(
            soldier_id=soldier.id,
            exemption_type_id=exemption_type.id,
            start_date=today,
            end_date=today,
        )
    )
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    exemption = admin_session.query(SoldierExemption).filter_by(soldier_id=soldier.id).one()
    exemption.end_date = date.fromordinal(today.toordinal() + 1)
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    setting = admin_session.get(SystemSetting, "eligibility.mitvahim_months")
    if setting is None:
        admin_session.add(SystemSetting(key="eligibility.mitvahim_months", value=7))
    else:
        setting.value = 7
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    scope_setting = admin_session.get(SystemSetting, "transparency.min_visible_level")
    if scope_setting is None:
        admin_session.add(SystemSetting(key="transparency.min_visible_level", value="every_soldier"))
    else:
        scope_setting.value = "every_soldier"
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    root_a = create_node(admin_session, level="department", name="cursor-rev-root-a")
    root_b = create_node(admin_session, level="department", name="cursor-rev-root-b")
    child = create_node(
        admin_session, level="team", name="cursor-rev-child", parent=root_a
    )
    revision = _revision(admin_session, "transparency_fairness_revision")
    child.parent_id = root_b.id
    child.path_ids = [root_b.id, child.id]
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    child.level = "branch"
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    child.commander_id = soldier.id
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    child.parent_id = root_a.id
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    soldier.hierarchy_node_id = child.id
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    scope_manager = create_soldier(admin_session, personal_number="cursor-rev-scope-manager")
    revision = _revision(admin_session, "transparency_fairness_revision")
    scope = DutyManagerScope(duty_manager_id=scope_manager.id, hierarchy_node_id=root_a.id)
    admin_session.add(scope)
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    scope.hierarchy_node_id = root_b.id
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
    revision += 1

    admin_session.delete(scope)
    admin_session.flush()
    assert _revision(admin_session, "transparency_fairness_revision") == revision + 1
