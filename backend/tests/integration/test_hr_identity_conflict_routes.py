"""Admin endpoints for HR sync identity conflicts."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import select

from app.db.models import AuditLog, HierarchyNode, HrIdentityConflict, HrPreferredRecord, Soldier
from app.services.hr.client import HrApiClient
from app.services.hr.person_sync import run_person_sync
from app.services.identity_write import assign_soldier_email
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_soldier

BASE = "https://hr.example.internal"
URL = "/api/admin/hr-sync"


def _holding(session):
    node = HierarchyNode(level="unit", name="Holding", parent_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    set_setting(session, "system.holding_node_id", str(node.id), actor_id=None)
    session.commit()


def _rec(pn, **extra):
    payload = {"personalNumber": pn, "fullName": f"Soldier {pn}"}
    payload.update(extra)
    return payload


def _sync(session, payloads):
    import asyncio

    async def go():
        with respx.mock(base_url=BASE, assert_all_called=False) as mock:
            mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
                return_value=httpx.Response(200, json=payloads))
            mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
                return_value=httpx.Response(200, json=[]))
            async with HrApiClient(base_url=BASE, api_key="k") as c:
                return await run_person_sync(session, c)

    run = asyncio.run(go())
    session.expire_all()
    return run


FEED = [
    _rec("r-1", fullName="First", mail="first@x.example", t_personID="T1"),
    _rec("r-1", fullName="Second", mail="second@x.example", t_personID="T2"),
]


def _setup(session, feed=FEED):
    _holding(session)
    admin = create_soldier(session, personal_number="r-admin", role="admin")
    run = _sync(session, feed)
    conflict = session.execute(select(HrIdentityConflict)).scalars().first()
    return admin, run, conflict


def test_endpoints_require_admin(client, admin_session):
    admin, _run, conflict = _setup(admin_session)
    plain = create_soldier(admin_session, personal_number="r-plain")
    calls = [
        ("get", f"{URL}/identity-conflicts", None),
        ("post", f"{URL}/identity-conflicts/{conflict.id}/acknowledge", None),
        ("post", f"{URL}/identity-conflicts/{conflict.id}/choose", {"candidate_index": 0}),
        ("get", f"{URL}/preferred-records", None),
        ("delete", f"{URL}/preferred-records/r-1", None),
    ]
    for method, url, body in calls:
        kw = {"json": body} if body is not None else {}
        assert getattr(client, method)(url, **kw).status_code in (401, 403), url
        assert getattr(client, method)(url, headers=auth_headers(plain), **kw).status_code == 403, url


def test_list_shows_candidates_side_by_side_with_applied_marked(client, admin_session):
    admin, run, conflict = _setup(admin_session)
    r = client.get(f"{URL}/identity-conflicts", headers=auth_headers(admin))
    assert r.status_code == 200
    [item] = r.json()["items"]
    assert (item["kind"], item["status"], item["reason"], item["applied_index"]) == (
        "duplicate_personal_number", "open", "latest", 1)
    assert item["personal_number"] == "r-1"
    assert item["hr_person_sync_id"] == str(run.id)
    c0, c1 = item["candidates"]
    assert (c0["is_applied"], c1["is_applied"]) == (False, True)
    assert c0["payload"]["fullName"] == "First" and c1["payload"]["fullName"] == "Second"
    assert (c0["key_type"], c0["key_value"]) == ("t_person_id", "T1")
    assert c0["choosable"] is True and c0["invalid_reason"] is None
    assert item["preferred_record"] is None


def test_list_marks_candidate_with_invalid_email_not_choosable(client, admin_session):
    feed = [_rec("r-2", t_personID="T1", mail="bad"), _rec("r-2", t_personID="T2", mail="ok@x.example")]
    admin, _run, _c = _setup(admin_session, feed)
    [item] = client.get(f"{URL}/identity-conflicts", headers=auth_headers(admin)).json()["items"]
    c0, c1 = item["candidates"]
    assert (c0["choosable"], c0["invalid_reason"]) == (False, "email_invalid")
    assert c1["choosable"] is True


def test_list_status_filter_and_collision_conflicts(client, admin_session):
    _holding(admin_session)
    owner = create_soldier(admin_session, personal_number="r-owner", full_name="Owner")
    assign_soldier_email(admin_session, owner, "taken@x.example")
    admin = create_soldier(admin_session, personal_number="r-admin", role="admin")
    admin_session.commit()
    _sync(admin_session, [_rec("r-3", mail="taken@x.example")])
    h = auth_headers(admin)
    [item] = client.get(f"{URL}/identity-conflicts", headers=h).json()["items"]
    assert item["kind"] == "email_collision"
    assert item["colliding_soldiers"] == [
        {"soldier_id": str(owner.id), "full_name": "Owner", "personal_number": "r-owner"}]
    assert item["candidates"][0]["choosable"] is False
    assert client.get(f"{URL}/identity-conflicts?status=resolved", headers=h).json()["items"] == []
    assert len(client.get(f"{URL}/identity-conflicts?status=all", headers=h).json()["items"]) == 1
    assert client.get(f"{URL}/identity-conflicts?status=nope", headers=h).status_code == 422


def test_acknowledge_silences_and_audits(client, admin_session):
    admin, _run, conflict = _setup(admin_session)
    h = auth_headers(admin)
    r = client.post(f"{URL}/identity-conflicts/{conflict.id}/acknowledge", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert client.get(f"{URL}/identity-conflicts", headers=h).json()["items"] == []
    ack = client.get(f"{URL}/identity-conflicts?status=acknowledged", headers=h).json()["items"]
    assert len(ack) == 1
    assert _sync(admin_session, FEED).conflict_count == 0
    audit = admin_session.execute(
        select(AuditLog).where(AuditLog.action == "hr_sync.identity_conflict.acknowledge")).scalar_one()
    assert audit.actor_id == admin.id and audit.entity_id == conflict.id
    # acknowledging twice is rejected
    assert client.post(f"{URL}/identity-conflicts/{conflict.id}/acknowledge", headers=h).status_code == 409


def test_unknown_conflict_is_404(client, admin_session):
    admin, _run, _c = _setup(admin_session)
    import uuid
    h = auth_headers(admin)
    assert client.post(f"{URL}/identity-conflicts/{uuid.uuid4()}/acknowledge", headers=h).status_code == 404
    assert client.post(f"{URL}/identity-conflicts/{uuid.uuid4()}/choose", json={"candidate_index": 0},
                       headers=h).status_code == 404


def test_choose_applies_now_stores_preference_resolves_and_audits(client, admin_session):
    admin, _run, conflict = _setup(admin_session)
    assert admin_session.execute(select(Soldier).where(Soldier.personal_number == "r-1")).scalar_one().full_name == "Second"
    h = auth_headers(admin)
    r = client.post(f"{URL}/identity-conflicts/{conflict.id}/choose", json={"candidate_index": 0}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["chosen_index"]) == ("resolved", 0)
    admin_session.expire_all()
    soldier = admin_session.execute(select(Soldier).where(Soldier.personal_number == "r-1")).scalar_one()
    assert (soldier.full_name, soldier.email) == ("First", "first@x.example")
    pref = admin_session.execute(select(HrPreferredRecord)).scalar_one()
    assert (pref.personal_number, pref.key_type, pref.key_value, pref.chosen_by) == (
        "r-1", "t_person_id", "T1", admin.id)
    assert admin_session.execute(
        select(AuditLog).where(AuditLog.action == "hr_sync.identity_conflict.choose")).scalar_one().actor_id == admin.id
    # remembered choice: next syncs apply it with no warning
    for _ in range(2):
        run = _sync(admin_session, FEED)
        assert run.conflict_count == 0
        assert admin_session.execute(select(Soldier).where(Soldier.personal_number == "r-1")).scalar_one().full_name == "First"
    prefs = client.get(f"{URL}/preferred-records", headers=h).json()["items"]
    assert [(p["personal_number"], p["key_type"], p["key_value"]) for p in prefs] == [("r-1", "t_person_id", "T1")]
    assert prefs[0]["chosen_by_name"]


def test_choose_invalid_candidates_are_rejected_without_side_effects(client, admin_session):
    feed = [_rec("r-4", t_personID="T1", mail="bad"), _rec("r-4", t_personID="T2", mail="ok@x.example")]
    admin, _run, conflict = _setup(admin_session, feed)
    h = auth_headers(admin)
    url = f"{URL}/identity-conflicts/{conflict.id}/choose"
    r = client.post(url, json={"candidate_index": 0}, headers=h)
    assert (r.status_code, r.json()["detail"]) == (400, "email_invalid")
    assert client.post(url, json={"candidate_index": 5}, headers=h).status_code == 400
    assert admin_session.execute(select(HrPreferredRecord)).first() is None
    admin_session.expire_all()
    assert admin_session.get(HrIdentityConflict, conflict.id).status == "open"


def test_choose_candidate_colliding_with_another_soldier_is_rejected(client, admin_session):
    _holding(admin_session)
    owner = create_soldier(admin_session, personal_number="r-owner")
    assign_soldier_email(admin_session, owner, "first@x.example")
    admin = create_soldier(admin_session, personal_number="r-admin", role="admin")
    admin_session.commit()
    _sync(admin_session, FEED)
    conflict = admin_session.execute(
        select(HrIdentityConflict).where(HrIdentityConflict.kind == "duplicate_personal_number")).scalar_one()
    r = client.post(f"{URL}/identity-conflicts/{conflict.id}/choose", json={"candidate_index": 0},
                    headers=auth_headers(admin))
    assert (r.status_code, r.json()["detail"]) == (400, "email_taken")


def test_choose_requires_unique_key_among_candidates(client, admin_session):
    feed = [_rec("r-5", t_personID="T1", mail="a@x.example"), _rec("r-5", t_personID="T1", mail="b@x.example")]
    admin, _run, conflict = _setup(admin_session, feed)
    r = client.post(f"{URL}/identity-conflicts/{conflict.id}/choose", json={"candidate_index": 0},
                    headers=auth_headers(admin))
    assert (r.status_code, r.json()["detail"]) == (400, "candidate_key_not_unique")


def test_choose_on_non_duplicate_conflict_is_rejected(client, admin_session):
    admin, _run, _c = _setup(admin_session, [_rec("r-6", mail="bad")])
    conflict = admin_session.execute(select(HrIdentityConflict)).scalar_one()
    r = client.post(f"{URL}/identity-conflicts/{conflict.id}/choose", json={"candidate_index": 0},
                    headers=auth_headers(admin))
    assert (r.status_code, r.json()["detail"]) == (400, "not_a_duplicate_conflict")


def test_choose_resolved_conflict_is_409(client, admin_session):
    admin, _run, conflict = _setup(admin_session)
    h = auth_headers(admin)
    url = f"{URL}/identity-conflicts/{conflict.id}/choose"
    assert client.post(url, json={"candidate_index": 0}, headers=h).status_code == 200
    assert client.post(url, json={"candidate_index": 1}, headers=h).status_code == 409


def test_clear_preference_restores_default_and_audits(client, admin_session):
    admin, _run, conflict = _setup(admin_session)
    h = auth_headers(admin)
    client.post(f"{URL}/identity-conflicts/{conflict.id}/choose", json={"candidate_index": 0}, headers=h)
    r = client.delete(f"{URL}/preferred-records/r-1", headers=h)
    assert r.status_code == 204
    assert admin_session.execute(select(HrPreferredRecord)).first() is None
    assert admin_session.execute(
        select(AuditLog).where(AuditLog.action == "hr_sync.preferred_record.clear")).scalar_one().actor_id == admin.id
    run = _sync(admin_session, FEED)
    assert run.conflict_count == 1  # warns again; default (latest) applies
    admin_session.expire_all()
    assert admin_session.execute(select(Soldier).where(Soldier.personal_number == "r-1")).scalar_one().full_name == "Second"
    assert client.delete(f"{URL}/preferred-records/r-1", headers=h).status_code == 404


def test_list_shows_remembered_choice_marker_on_new_warning(client, admin_session):
    admin, _run, conflict = _setup(admin_session)
    h = auth_headers(admin)
    client.post(f"{URL}/identity-conflicts/{conflict.id}/choose", json={"candidate_index": 0}, headers=h)
    # preferred record leaves the feed -> stale warning that names the preference
    _sync(admin_session, [_rec("r-1", t_personID="T7", mail="x@x.example"), _rec("r-1", t_personID="T8", mail="y@x.example")])
    [item] = client.get(f"{URL}/identity-conflicts", headers=h).json()["items"]
    assert item["reason"] == "preferred_stale"
    assert item["preferred_record"]["key_type"] == "t_person_id"
    assert item["preferred_record"]["key_value"] == "T1"
