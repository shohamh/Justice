from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import HierarchyNode, HrHierarchyNodeMap, NotificationType
from app.services.hr.client import HrApiClient
from app.services.hr.person_sync import resolve_placement_node_id
from app.services.hr.schemas import HrUser
from app.services.settings_loader import set_setting


def _hr_user(**overrides: object) -> HrUser:
    defaults: dict[str, object] = dict(
        full_name="ישראל ישראלי", personal_number="ps-1",
        team_id=None, mador_id=None, branch_id=None,
        department_id=None, shetach_id=None, unit_id=None,
    )
    defaults.update(overrides)
    return HrUser(**defaults)


def _node(session, name: str) -> HierarchyNode:
    node = HierarchyNode(level="unit", name=name, parent_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.commit()
    return node


def _holding_node(session) -> HierarchyNode:
    node = _node(session, "Holding")
    set_setting(session, "system.holding_node_id", str(node.id), actor_id=None)
    session.commit()
    return node


def test_resolve_placement_prefers_team_id_over_others(admin_session):
    team_node = _node(admin_session, "Team Node")
    mador_node = _node(admin_session, "Mador Node")
    admin_session.add_all([
        HrHierarchyNodeMap(hr_group_id="team-1", node_id=team_node.id),
        HrHierarchyNodeMap(hr_group_id="mador-1", node_id=mador_node.id),
    ])
    admin_session.commit()

    user = _hr_user(team_id="team-1", mador_id="mador-1")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == team_node.id


def test_resolve_placement_falls_back_through_priority_order(admin_session):
    branch_node = _node(admin_session, "Branch Node")
    admin_session.add(HrHierarchyNodeMap(hr_group_id="branch-1", node_id=branch_node.id))
    admin_session.commit()

    # team_id and mador_id present but unresolved; branch_id resolves.
    user = _hr_user(team_id="team-unresolved", mador_id="mador-unresolved", branch_id="branch-1")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == branch_node.id


def test_resolve_placement_no_ids_present_uses_holding_node(admin_session):
    holding = _holding_node(admin_session)

    user = _hr_user()
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == holding.id


def test_resolve_placement_unresolved_ids_use_holding_node(admin_session):
    holding = _holding_node(admin_session)

    user = _hr_user(team_id="nonexistent", unit_id="also-nonexistent")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == holding.id


import secrets

from app.db.models import Soldier, SoldierHrProfile
from app.services.hr.mapping import HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.person_sync import _apply_new_person, _mark_held


def _mapped(**overrides: object) -> MappedSoldierFields:
    defaults: dict[str, object] = dict(full_name="ישראל ישראלי", personal_number="ps-new-1")
    defaults.update(overrides)
    return MappedSoldierFields(**defaults)


def test_apply_new_person_creates_soldier_with_placeholder_password(admin_session):
    holding = _holding_node(admin_session)
    user = _hr_user(personal_number="ps-new-1", full_name="ישראל ישראלי")
    mapped = _mapped()

    soldier, profile = _apply_new_person(admin_session, user, mapped)
    admin_session.commit()

    assert soldier.personal_number == "ps-new-1"
    assert soldier.must_change_password is True
    assert soldier.hierarchy_node_id == holding.id
    assert profile.soldier_id == soldier.id
    assert profile.sync_status == "synced"


def test_apply_new_person_links_existing_soldier_without_touching_password(admin_session):
    from tests.helpers import create_soldier

    _holding_node(admin_session)
    existing = create_soldier(admin_session, personal_number="ps-existing-1")
    original_hash = existing.password_hash
    original_role = existing.role

    user = _hr_user(personal_number="ps-existing-1", full_name=existing.full_name)
    mapped = _mapped(personal_number="ps-existing-1", full_name=existing.full_name)

    soldier, profile = _apply_new_person(admin_session, user, mapped)
    admin_session.commit()

    assert soldier.id == existing.id
    assert soldier.password_hash == original_hash
    assert soldier.role == original_role
    assert profile.soldier_id == existing.id


def test_mark_held_creates_profile_without_soldier(admin_session):
    user = _hr_user(personal_number="ps-held-1")
    held = HeldForReview(personal_number="ps-held-1", reasons=["unmappable rank: 'x'"])

    profile = _mark_held(admin_session, user, held)
    admin_session.commit()

    assert profile.soldier_id is None
    assert profile.sync_status == "held_for_review"
    assert "unmappable rank" in profile.review_reason
    assert admin_session.query(Soldier).filter_by(personal_number="ps-held-1").first() is None


def test_mark_held_updates_existing_held_profile_not_duplicate(admin_session):
    user = _hr_user(personal_number="ps-held-2")
    held1 = HeldForReview(personal_number="ps-held-2", reasons=["first reason"])
    held2 = HeldForReview(personal_number="ps-held-2", reasons=["second reason"])

    _mark_held(admin_session, user, held1)
    admin_session.commit()
    _mark_held(admin_session, user, held2)
    admin_session.commit()

    rows = admin_session.query(SoldierHrProfile).filter_by(personal_number="ps-held-2").all()
    assert len(rows) == 1
    assert "second reason" in rows[0].review_reason


from app.services.hr.person_sync import _apply_existing_person


def _linked_profile(session, soldier) -> SoldierHrProfile:
    profile = SoldierHrProfile(
        personal_number=soldier.personal_number, raw_dto={}, soldier_id=soldier.id, sync_status="synced",
    )
    session.add(profile)
    session.commit()
    return profile


def test_apply_existing_person_updates_non_overridden_field(admin_session):
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="ps-upd-1")
    profile = _linked_profile(admin_session, soldier)
    user = _hr_user(personal_number="ps-upd-1")
    mapped = _mapped(personal_number="ps-upd-1", phone="050-1112222")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()
    admin_session.refresh(soldier)

    assert soldier.phone == "050-1112222"


def test_apply_existing_person_skips_overridden_field_and_records_divergence(admin_session):
    from sqlalchemy import select as sa_select
    from tests.helpers import create_soldier
    from app.db.models import AuditLog

    soldier = create_soldier(admin_session, personal_number="ps-upd-2")
    soldier.phone = "050-0000000"
    admin_session.commit()
    profile = _linked_profile(admin_session, soldier)
    profile.overridden_fields = ["phone"]
    admin_session.commit()

    user = _hr_user(personal_number="ps-upd-2")
    mapped = _mapped(personal_number="ps-upd-2", phone="050-9998888")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()
    admin_session.refresh(soldier)

    assert soldier.phone == "050-0000000"
    entries = admin_session.execute(
        sa_select(AuditLog).where(AuditLog.action == "hr_sync.field_skipped_overridden")
    ).scalars().all()
    assert len(entries) == 1


def test_apply_existing_person_reruns_dependent_logic_on_rank_change(admin_session, monkeypatch):
    from tests.helpers import create_soldier
    import app.services.hr.person_sync as person_sync_module

    soldier = create_soldier(admin_session, personal_number="ps-upd-3")
    profile = _linked_profile(admin_session, soldier)
    user = _hr_user(personal_number="ps-upd-3")
    mapped = _mapped(personal_number="ps-upd-3", rank="רסל")

    calls = []
    monkeypatch.setattr(
        person_sync_module, "_reset_rank_advancement",
        lambda session, s, *, since: calls.append(("rank", s.id)),
    )
    monkeypatch.setattr(
        person_sync_module, "recheck_soldier_assignments",
        lambda session, soldier_id: calls.append(("eligibility", soldier_id)),
    )

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert ("rank", soldier.id) in calls
    assert ("eligibility", soldier.id) in calls


def test_apply_existing_person_does_not_rerun_dependent_logic_when_untracked_field_changes(admin_session, monkeypatch):
    from tests.helpers import create_soldier
    import app.services.hr.person_sync as person_sync_module

    soldier = create_soldier(admin_session, personal_number="ps-upd-4")
    profile = _linked_profile(admin_session, soldier)
    user = _hr_user(personal_number="ps-upd-4")
    mapped = _mapped(personal_number="ps-upd-4", phone="050-1231234")

    calls = []
    monkeypatch.setattr(
        person_sync_module, "_reset_rank_advancement",
        lambda session, s, *, since: calls.append("rank"),
    )
    monkeypatch.setattr(
        person_sync_module, "recheck_soldier_assignments",
        lambda session, soldier_id: calls.append("eligibility"),
    )

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert calls == []


def test_apply_existing_person_flips_vanished_back_to_synced(admin_session):
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="ps-upd-5")
    profile = _linked_profile(admin_session, soldier)
    profile.sync_status = "vanished"
    admin_session.commit()

    user = _hr_user(personal_number="ps-upd-5")
    mapped = _mapped(personal_number="ps-upd-5")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert profile.sync_status == "synced"


import httpx
import respx

from app.db.models import HrPersonSync, HrPersonSyncError, Notification
from app.services.hr.person_sync import run_person_sync


def _user_payload(personal_number: str, **overrides: object) -> dict:
    payload = {"personalNumber": personal_number, "fullName": f"Soldier {personal_number}"}
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_run_person_sync_creates_new_people(admin_session):
    _holding_node(admin_session)
    payload = [_user_payload("ps-run-1"), _user_payload("ps-run-2")]
    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=payload)
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.total_fetched == 2
    assert run.created_count == 2


@pytest.mark.asyncio
async def test_run_person_sync_marks_vanished_person(admin_session):
    from tests.helpers import create_soldier
    from app.db.models import SoldierHrProfile

    _holding_node(admin_session)
    soldier = create_soldier(admin_session, personal_number="ps-vanish-1")
    admin_session.add(SoldierHrProfile(
        personal_number="ps-vanish-1", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
    ))
    admin_session.commit()

    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.vanished_count == 1
    profile = admin_session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.personal_number == "ps-vanish-1")
    ).scalar_one()
    assert profile.sync_status == "vanished"


@pytest.mark.asyncio
async def test_run_person_sync_aborts_on_anomaly_and_notifies_admins(admin_session):
    from tests.helpers import create_soldier

    admin = create_soldier(admin_session, personal_number="ps-admin-1", role="admin")
    prior_run = HrPersonSync(status="completed", total_fetched=100)
    admin_session.add(prior_run)
    admin_session.commit()

    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[_user_payload("ps-only-one")])
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "aborted_anomaly"
    assert run.error_message is not None
    notifications = admin_session.execute(
        select(Notification).where(Notification.soldier_id == admin.id)
    ).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.hr_sync_anomaly_aborted


@pytest.mark.asyncio
async def test_run_person_sync_first_run_has_no_baseline_and_proceeds(admin_session):
    _holding_node(admin_session)
    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[_user_payload("ps-first-1")])
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 1


@pytest.mark.asyncio
async def test_run_person_sync_per_person_error_does_not_abort_run(admin_session, monkeypatch):
    import app.services.hr.person_sync as person_sync_module

    _holding_node(admin_session)
    payload = [_user_payload("ps-err-1"), _user_payload("ps-err-2")]

    original = person_sync_module._apply_new_person
    call_count = {"n": 0}

    def _flaky_apply_new_person(session, user, mapped):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated failure")
        return original(session, user, mapped)

    monkeypatch.setattr(person_sync_module, "_apply_new_person", _flaky_apply_new_person)

    with respx.mock(base_url="https://hr.example.internal", assert_all_called=False) as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=payload)
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 1
    assert run.error_count == 1
    errors = admin_session.execute(
        select(HrPersonSyncError).where(HrPersonSyncError.hr_person_sync_id == run.id)
    ).scalars().all()
    assert len(errors) == 1
    assert errors[0].personal_number == "ps-err-1"
