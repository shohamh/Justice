from __future__ import annotations

import uuid

from app.db.models import HierarchyNode
from app.services.hr.hierarchy_sync import GroupResolution, _resolve_group
from app.services.hr.schemas import HrGroup


def _group(id: str, name: str, parent_id: str | None = None, kind: str = "unit") -> HrGroup:
    return HrGroup(id=id, name=name, kind=kind, parent_id=parent_id)


def test_resolve_group_root_with_no_existing_match_creates_node(admin_session):
    group = _group("hr-1", "New Unit", kind="unit")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "created"
    assert resolution.level == "unit"
    assert resolution.reason is None
    node = admin_session.get(HierarchyNode, resolution.resolved_node_id)
    assert node.name == "New Unit"
    assert node.parent_id is None


def test_resolve_group_root_matching_existing_node_by_name(admin_session):
    existing = HierarchyNode(level="unit", name="Existing Unit", parent_id=None, path_ids=[])
    admin_session.add(existing)
    admin_session.flush()
    existing.path_ids = [existing.id]
    admin_session.commit()

    group = _group("hr-1", "Existing Unit", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "matched"
    assert resolution.resolved_node_id == existing.id
    assert resolution.reason is None


def test_resolve_group_child_with_resolved_parent_creates_under_it(admin_session):
    parent_node_id = uuid.uuid4()
    parent_node = HierarchyNode(level="unit", name="Parent Unit", parent_id=None, path_ids=[])
    admin_session.add(parent_node)
    admin_session.flush()
    parent_node.path_ids = [parent_node.id]
    admin_session.commit()

    group = _group("hr-child", "Child Branch", parent_id="hr-parent", kind="branch")
    resolution = _resolve_group(
        admin_session, group, hr_id_to_node_id={"hr-parent": parent_node.id}
    )
    admin_session.commit()

    assert resolution.action == "created"
    node = admin_session.get(HierarchyNode, resolution.resolved_node_id)
    assert node.parent_id == parent_node.id
    assert node.level == "branch"


def test_resolve_group_unmapped_kind_is_held(admin_session):
    group = _group("hr-1", "Mystery Group", kind="some_unknown_kind")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "some_unknown_kind" in resolution.reason


def test_resolve_group_mapped_level_not_configured_is_held(admin_session, monkeypatch):
    # HR_GROUP_KIND_TO_LEVEL_MAP only maps to level keys the test DB
    # template happens to seed (see Global Constraints), so exercising the
    # "kind maps to *something*, but that level key isn't configured in
    # HierarchyLevelType" branch needs a map entry pointing at a level key
    # that's guaranteed absent — monkeypatch the module-level dict for the
    # duration of this test rather than relying on DB seeding quirks.
    import app.services.hr.hierarchy_sync as hierarchy_sync_module

    monkeypatch.setitem(
        hierarchy_sync_module.HR_GROUP_KIND_TO_LEVEL_MAP, "ghost_kind", "level_key_that_does_not_exist"
    )
    group = _group("hr-1", "Ghost Group", kind="ghost_kind")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "level_key_that_does_not_exist" in resolution.reason


def test_resolve_group_unresolved_parent_is_held(admin_session):
    group = _group("hr-child", "Orphaned Child", parent_id="hr-parent-never-resolved", kind="branch")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "hr-parent-never-resolved" in resolution.reason


def test_resolve_group_same_name_different_parents_both_resolve_independently(admin_session):
    parent_a = HierarchyNode(level="unit", name="Parent A", parent_id=None, path_ids=[])
    parent_b = HierarchyNode(level="unit", name="Parent B", parent_id=None, path_ids=[])
    admin_session.add_all([parent_a, parent_b])
    admin_session.flush()
    parent_a.path_ids = [parent_a.id]
    parent_b.path_ids = [parent_b.id]
    admin_session.commit()

    group_a = _group("hr-a", "Shared Name", parent_id="hr-parent-a", kind="branch")
    group_b = _group("hr-b", "Shared Name", parent_id="hr-parent-b", kind="branch")
    hr_id_to_node_id = {"hr-parent-a": parent_a.id, "hr-parent-b": parent_b.id}

    resolution_a = _resolve_group(admin_session, group_a, hr_id_to_node_id=hr_id_to_node_id)
    admin_session.commit()
    resolution_b = _resolve_group(admin_session, group_b, hr_id_to_node_id=hr_id_to_node_id)
    admin_session.commit()

    assert resolution_a.action == "created"
    assert resolution_b.action == "created"
    assert resolution_a.resolved_node_id != resolution_b.resolved_node_id
