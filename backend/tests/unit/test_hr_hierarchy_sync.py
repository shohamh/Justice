from __future__ import annotations

import uuid
from unittest.mock import patch

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.db.models import AuditLog, HierarchyNode, HrHierarchySync
from app.services import hierarchy as hierarchy_service
from app.services.hr.client import HrApiClient
from app.services.hr.hierarchy_sync import _resolve_group, run_hierarchy_sync
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


def test_resolve_group_child_rank_not_below_parent_is_held(admin_session):
    # "team" is the deepest seeded level (rank 7); a group mapped to
    # "branch" (rank 5) resolving under a "team" parent is a rank
    # inversion create_node would reject — _resolve_group must catch this
    # itself and hold, not let create_node's HierarchyError propagate.
    parent_node = HierarchyNode(level="team", name="Deep Team", parent_id=None, path_ids=[])
    admin_session.add(parent_node)
    admin_session.flush()
    parent_node.path_ids = [parent_node.id]
    admin_session.commit()

    group = _group("hr-child", "Inverted Branch", parent_id="hr-parent", kind="branch")
    resolution = _resolve_group(
        admin_session, group, hr_id_to_node_id={"hr-parent": parent_node.id}
    )

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "branch" in resolution.reason
    assert "team" in resolution.reason
    created_count = admin_session.execute(
        select(func.count()).select_from(HierarchyNode).where(HierarchyNode.name == "Inverted Branch")
    ).scalar_one()
    assert created_count == 0


def test_resolve_group_ambiguous_existing_match_is_held(admin_session):
    dup_a = HierarchyNode(level="unit", name="Dup Root", parent_id=None, path_ids=[])
    dup_b = HierarchyNode(level="unit", name="Dup Root", parent_id=None, path_ids=[])
    admin_session.add_all([dup_a, dup_b])
    admin_session.flush()
    dup_a.path_ids = [dup_a.id]
    dup_b.path_ids = [dup_b.id]
    admin_session.commit()

    group = _group("hr-1", "Dup Root", kind="unit")

    # Must not raise sqlalchemy.exc.MultipleResultsFound.
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "2" in resolution.reason
    assert "Dup Root" in resolution.reason


@pytest.mark.asyncio
async def test_run_hierarchy_sync_creates_root_and_child(admin_session):
    groups_payload = [
        {"id": "hr-root", "name": "Root Unit", "kind": "unit", "parentId": None},
        {"id": "hr-child", "name": "Child Branch", "kind": "branch", "parentId": "hr-root"},
    ]
    # assert_all_called=False: iter_groups stops as soon as a page returns
    # fewer than page_size (200) records, so the page=2 route below is
    # registered defensively but is never actually hit for a 2-item payload
    # (see test_iter_groups_stops_on_short_page in
    # app/services/hr/tests/test_client_pagination.py for the same contract).
    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 2
    assert run.matched_count == 0
    assert run.held_count == 0
    assert len(run.parsed_state) == 2
    assert {entry["action"] for entry in run.parsed_state} == {"created"}


@pytest.mark.asyncio
async def test_run_hierarchy_sync_mixed_matched_created_held(admin_session):
    existing = HierarchyNode(level="unit", name="Already There", parent_id=None, path_ids=[])
    admin_session.add(existing)
    admin_session.flush()
    existing.path_ids = [existing.id]
    admin_session.commit()

    groups_payload = [
        {"id": "hr-existing", "name": "Already There", "kind": "unit", "parentId": None},
        {"id": "hr-new", "name": "New Root", "kind": "unit", "parentId": None},
        {"id": "hr-bad-kind", "name": "Mystery", "kind": "no_such_kind", "parentId": None},
    ]
    # assert_all_called=False: see comment in
    # test_run_hierarchy_sync_creates_root_and_child above — the page=2
    # route is never hit for a 3-item (< page_size) payload.
    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.matched_count == 1
    assert run.created_count == 1
    assert run.held_count == 1


@pytest.mark.asyncio
async def test_run_hierarchy_sync_empty_group_list(admin_session):
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 0
    assert run.matched_count == 0
    assert run.held_count == 0
    assert run.parsed_state == []


@pytest.mark.asyncio
async def test_run_hierarchy_sync_failure_rolls_back_and_records_error(admin_session):
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(500, text="HR server error")
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "failed"
    assert run.error_message is not None
    all_runs = admin_session.execute(select(HrHierarchySync)).scalars().all()
    assert len(all_runs) == 1
    assert all_runs[0].id == run.id


@pytest.mark.asyncio
async def test_run_hierarchy_sync_partial_failure_discards_already_created_node(admin_session):
    """A genuinely unexpected exception mid-loop (e.g. a DB blip) must roll
    back everything from this run, including nodes already flushed for
    earlier groups in the same run — not just mark the run row failed."""
    groups_payload = [
        {"id": "hr-root", "name": "Root Unit", "kind": "unit", "parentId": None},
        {"id": "hr-second", "name": "Second Root", "kind": "unit", "parentId": None},
    ]

    real_create_node = hierarchy_service.create_node
    call_count = {"n": 0}

    def flaky_create_node(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated DB connectivity blip")
        return real_create_node(*args, **kwargs)

    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            with patch(
                "app.services.hr.hierarchy_sync.hierarchy_service.create_node",
                side_effect=flaky_create_node,
            ):
                run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "failed"
    assert run.created_count == 0
    assert run.parsed_state == []

    node_count = admin_session.execute(
        select(func.count()).select_from(HierarchyNode)
    ).scalar_one()
    assert node_count == 0

    audit_count = admin_session.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "hierarchy_node.create")
    ).scalar_one()
    assert audit_count == 0


@pytest.mark.asyncio
async def test_run_hierarchy_sync_reversed_order_still_creates_3_level_tree(admin_session):
    """Submit a 3-level tree grandchild-first to prove _topological_order's
    reordering is load-bearing inside the real orchestration loop, not just
    in its own isolated unit tests."""
    groups_payload = [
        {"id": "hr-team", "name": "Team X", "kind": "team", "parentId": "hr-branch"},
        {"id": "hr-branch", "name": "Branch X", "kind": "branch", "parentId": "hr-root"},
        {"id": "hr-root", "name": "Root X", "kind": "unit", "parentId": None},
    ]
    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 3
    assert run.held_count == 0

    by_hr_id = {entry["hr_group_id"]: entry for entry in run.parsed_state}
    assert {entry["action"] for entry in by_hr_id.values()} == {"created"}

    root_node = admin_session.get(HierarchyNode, uuid.UUID(by_hr_id["hr-root"]["resolved_node_id"]))
    branch_node = admin_session.get(HierarchyNode, uuid.UUID(by_hr_id["hr-branch"]["resolved_node_id"]))
    team_node = admin_session.get(HierarchyNode, uuid.UUID(by_hr_id["hr-team"]["resolved_node_id"]))

    assert root_node.parent_id is None
    assert branch_node.parent_id == root_node.id
    assert team_node.parent_id == branch_node.id


@pytest.mark.asyncio
async def test_run_hierarchy_sync_held_parent_cascades_to_held_child(admin_session):
    """A parent group with an unmapped kind is held; its child, submitted
    in the same real run, must cascade to held too because the parent
    never appears in hr_id_to_node_id — driven through the real
    iter_groups()-backed orchestration loop, not a hand-built dict."""
    groups_payload = [
        {"id": "hr-parent", "name": "Unmapped Parent", "kind": "some_unknown_kind", "parentId": None},
        {"id": "hr-child", "name": "Child Of Held", "kind": "unit", "parentId": "hr-parent"},
    ]
    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.held_count == 2
    assert run.created_count == 0

    by_hr_id = {entry["hr_group_id"]: entry for entry in run.parsed_state}
    assert by_hr_id["hr-parent"]["action"] == "held"
    assert by_hr_id["hr-child"]["action"] == "held"
    assert "hr-parent" in by_hr_id["hr-child"]["reason"]


def test_resolve_group_matched_upserts_node_map(admin_session):
    from app.db.models import HierarchyNode, HrHierarchyNodeMap

    existing = HierarchyNode(level="unit", name="Mapped Unit", parent_id=None, path_ids=[])
    admin_session.add(existing)
    admin_session.flush()
    existing.path_ids = [existing.id]
    admin_session.commit()

    group = _group("hr-map-1", "Mapped Unit", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "matched"
    row = admin_session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == "hr-map-1")
    ).scalar_one()
    assert row.node_id == existing.id


def test_resolve_group_created_upserts_node_map(admin_session):
    from app.db.models import HrHierarchyNodeMap

    group = _group("hr-map-2", "Brand New Unit", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "created"
    row = admin_session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == "hr-map-2")
    ).scalar_one()
    assert row.node_id == resolution.resolved_node_id


def test_resolve_group_node_map_upsert_is_idempotent_across_runs(admin_session):
    from app.db.models import HrHierarchyNodeMap

    group = _group("hr-map-3", "Idempotent Unit", kind="unit")
    _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()
    # Re-resolve the same group in a later "run" — should match (not create
    # a duplicate node) and update the same map row, not insert a second one.
    resolution2 = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution2.action == "matched"
    rows = admin_session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == "hr-map-3")
    ).scalars().all()
    assert len(rows) == 1


def test_resolve_group_same_name_different_level_no_longer_ambiguous(admin_session):
    from app.db.models import HierarchyNode

    existing_team = HierarchyNode(level="team", name="Signal", parent_id=None, path_ids=[])
    admin_session.add(existing_team)
    admin_session.flush()
    existing_team.path_ids = [existing_team.id]
    admin_session.commit()

    # A "unit"-kind HR group with the same name and same (root) parent as
    # the existing "team" node must NOT be treated as ambiguous — different
    # level means it's a different real-world entity, so this should create
    # a new node rather than holding on "ambiguous match".
    group = _group("hr-map-4", "Signal", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "created"
    assert resolution.resolved_node_id != existing_team.id
