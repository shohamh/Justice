"""HR person sync: identity conflicts are detected, warned about, and never fail the run."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import (
    HierarchyNode,
    HrIdentityConflict,
    HrPersonSync,
    HrPersonSyncError,
    HrPreferredRecord,
    Soldier,
)
from app.services.hr.client import HrApiClient
from app.services.hr.errors import HrIdentityConflictError
from app.services.hr.person_sync import run_person_sync
from app.services.identity_write import assign_soldier_email
from app.services.settings_loader import set_setting
from tests.helpers import create_soldier

BASE = "https://hr.example.internal"


def _holding(session) -> None:
    node = HierarchyNode(level="unit", name="Holding", parent_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    set_setting(session, "system.holding_node_id", str(node.id), actor_id=None)
    session.commit()


def _rec(pn: str, **extra: object) -> dict:
    payload = {"personalNumber": pn, "fullName": f"Soldier {pn}"}
    payload.update(extra)
    return payload


async def _run(session, payloads: list[dict]) -> HrPersonSync:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=payloads)
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url=BASE, api_key="k") as client:
            run = await run_person_sync(session, client)
    session.expire_all()
    return run


def _soldier(session, pn: str) -> Soldier:
    return session.execute(select(Soldier).where(Soldier.personal_number == pn)).scalar_one()


def _conflicts(session, pn: str | None = None) -> list[HrIdentityConflict]:
    q = select(HrIdentityConflict)
    if pn:
        q = q.where(HrIdentityConflict.personal_number == pn)
    return list(session.execute(q.order_by(HrIdentityConflict.created_at)).scalars())


def _owner(session, email: str, pn: str = "owner-1") -> Soldier:
    s = create_soldier(session, personal_number=pn)
    assign_soldier_email(session, s, email)
    session.commit()
    return s


def test_error_is_a_value_error():
    assert issubclass(HrIdentityConflictError, ValueError)


async def test_clean_feed_has_no_conflicts(admin_session):
    _holding(admin_session)
    run = await _run(admin_session, [_rec("c-1", mail="a@x.example"), _rec("c-2", mail="b@x.example")])
    assert run.status == "completed"
    assert run.conflict_count == 0
    assert run.created_count == 2
    assert _conflicts(admin_session) == []


async def test_duplicate_personal_number_applies_latest_and_warns(admin_session, caplog):
    _holding(admin_session)
    feed = [
        _rec("d-1", fullName="First Name", mail="first@x.example", t_personID="T1"),
        _rec("d-2", mail="other@x.example"),
        _rec("d-1", fullName="Second Name", mail="second@x.example", t_personID="T2"),
    ]
    with caplog.at_level(logging.WARNING):
        run = await _run(admin_session, feed)
    assert run.status == "completed"
    assert run.error_count == 0
    assert run.conflict_count == 1
    assert run.created_count == 2
    s = _soldier(admin_session, "d-1")
    assert (s.full_name, s.email) == ("Second Name", "second@x.example")
    [c] = _conflicts(admin_session, "d-1")
    assert (c.kind, c.status, c.reason, c.applied_index) == ("duplicate_personal_number", "open", "latest", 1)
    assert [x["payload"]["fullName"] for x in c.candidates] == ["First Name", "Second Name"]
    assert [x["key_type"] for x in c.candidates] == ["t_person_id", "t_person_id"]
    assert c.hr_person_sync_id == run.id
    assert "first@x.example" not in caplog.text and "second@x.example" not in caplog.text
    assert "d-1" in caplog.text


async def test_identical_duplicate_payloads_still_warn(admin_session):
    _holding(admin_session)
    run = await _run(admin_session, [_rec("d-3", mail="same@x.example")] * 2)
    assert run.conflict_count == 1
    assert run.created_count == 1
    [c] = _conflicts(admin_session, "d-3")
    assert len(c.candidates) == 2


async def test_duplicate_is_redetected_each_sync_and_acknowledged_one_is_quiet(admin_session):
    _holding(admin_session)
    feed = [_rec("d-4", fullName="A"), _rec("d-4", fullName="B")]
    first = await _run(admin_session, feed)
    second = await _run(admin_session, feed)
    assert (first.conflict_count, second.conflict_count) == (1, 1)
    [c] = _conflicts(admin_session, "d-4")  # reused, not duplicated
    assert c.hr_person_sync_id == second.id
    c.status = "acknowledged"
    admin_session.commit()
    third = await _run(admin_session, feed)
    assert third.conflict_count == 0
    assert _conflicts(admin_session, "d-4")[0].status == "acknowledged"
    # inputs changed -> reopens
    fourth = await _run(admin_session, [_rec("d-4", fullName="A"), _rec("d-4", fullName="C")])
    assert fourth.conflict_count == 1
    assert _conflicts(admin_session, "d-4")[0].status == "open"


async def test_other_people_still_sync_with_a_duplicate(admin_session):
    _holding(admin_session)
    run = await _run(admin_session, [_rec("d-5"), _rec("d-6"), _rec("d-5"), _rec("d-7")])
    assert run.status == "completed"
    assert run.created_count == 3
    assert {s.personal_number for s in admin_session.execute(select(Soldier)).scalars()} == {"d-5", "d-6", "d-7"}


async def test_email_colliding_with_another_soldier_is_not_applied_but_other_fields_sync(admin_session, caplog):
    _holding(admin_session)
    _owner(admin_session, "taken@x.example")
    create_soldier(admin_session, personal_number="e-1", full_name="Old Name")
    admin_session.commit()
    with caplog.at_level(logging.WARNING):
        run = await _run(admin_session, [_rec("e-1", fullName="New Name", mail="TAKEN@x.example")])
    assert run.status == "completed" and run.error_count == 0
    assert run.conflict_count == 1
    s = _soldier(admin_session, "e-1")
    assert (s.full_name, s.email) == ("New Name", None)
    [c] = _conflicts(admin_session, "e-1")
    assert (c.kind, c.reason, c.applied_index) == ("email_collision", "email_not_applied", 0)
    assert len(c.colliding_soldier_ids) == 1
    assert "taken@x.example" not in caplog.text.lower()


async def test_ad_username_colliding_with_another_soldier_is_not_applied(admin_session):
    _holding(admin_session)
    _owner(admin_session, "dude@corp.example")
    run = await _run(admin_session, [_rec("e-2", mail="dude@other.example")])
    assert run.conflict_count == 1
    assert _soldier(admin_session, "e-2").email is None
    [c] = _conflicts(admin_session, "e-2")
    assert c.kind == "ad_username_collision"


async def test_invalid_hr_email_is_warned_and_person_still_synced(admin_session):
    _holding(admin_session)
    run = await _run(admin_session, [_rec("e-3", mail="not-an-email")])
    assert run.status == "completed" and run.created_count == 1 and run.conflict_count == 1
    assert _soldier(admin_session, "e-3").email is None
    assert _conflicts(admin_session, "e-3")[0].kind == "email_invalid"


async def test_unchanged_own_email_is_not_a_collision(admin_session):
    _holding(admin_session)
    mine = _owner(admin_session, "me@x.example", pn="e-4")
    run = await _run(admin_session, [_rec("e-4", mail="ME@x.example", fullName="Renamed")])
    assert run.conflict_count == 0
    assert _soldier(admin_session, "e-4").full_name == "Renamed"
    assert _soldier(admin_session, "e-4").id == mine.id


async def test_collision_is_counted_in_the_run_not_as_an_error(admin_session):
    _holding(admin_session)
    _owner(admin_session, "taken@x.example")
    run = await _run(admin_session, [_rec("e-5", mail="taken@x.example")])
    assert run.error_count == 0
    assert admin_session.execute(select(HrPersonSyncError)).first() is None


# ── remembered choice ──────────────────────────────────────────────────────


def _prefer(session, pn, key_type, key_value):
    session.add(HrPreferredRecord(personal_number=pn, key_type=key_type, key_value=key_value))
    session.commit()


DUP = [
    _rec("p-1", fullName="First", mail="first@x.example", t_personID="T1"),
    _rec("p-1", fullName="Second", mail="second@x.example", t_personID="T2"),
]


async def test_preferred_record_is_applied_without_warning_on_every_sync(admin_session):
    _holding(admin_session)
    _prefer(admin_session, "p-1", "t_person_id", "T1")
    for _ in range(2):
        run = await _run(admin_session, DUP)
        assert run.conflict_count == 0
        assert _soldier(admin_session, "p-1").full_name == "First"
    assert _conflicts(admin_session) == []


async def test_preferred_by_username_and_mail_keys(admin_session):
    _holding(admin_session)
    _prefer(admin_session, "p-2", "username", "u-one")
    run = await _run(admin_session, [
        _rec("p-2", fullName="One", username="u-one", mail="one@x.example"),
        _rec("p-2", fullName="Two", username="u-two", mail="two@x.example"),
    ])
    assert run.conflict_count == 0 and _soldier(admin_session, "p-2").full_name == "One"
    _prefer(admin_session, "p-3", "mail", "a@x.example")
    run = await _run(admin_session, [
        _rec("p-3", fullName="A", mail=" A@X.example "), _rec("p-3", fullName="B", mail="b@x.example"),
    ])
    assert run.conflict_count == 0 and _soldier(admin_session, "p-3").full_name == "A"


async def test_stale_preference_falls_back_to_latest_warns_and_is_kept(admin_session):
    _holding(admin_session)
    _prefer(admin_session, "p-1", "t_person_id", "GONE")
    run = await _run(admin_session, DUP)
    assert run.conflict_count == 1
    assert _soldier(admin_session, "p-1").full_name == "Second"
    [c] = _conflicts(admin_session, "p-1")
    assert c.reason == "preferred_stale"
    assert admin_session.execute(select(HrPreferredRecord)).scalar_one().key_value == "GONE"


async def test_ambiguous_preference_falls_back_to_latest_and_warns(admin_session):
    _holding(admin_session)
    _prefer(admin_session, "p-4", "t_person_id", "T9")
    run = await _run(admin_session, [
        _rec("p-4", fullName="A", t_personID="T9", mail="a@x.example"),
        _rec("p-4", fullName="B", t_personID="T9", mail="b@x.example"),
    ])
    assert run.conflict_count == 1
    assert _soldier(admin_session, "p-4").full_name == "B"
    assert _conflicts(admin_session, "p-4")[0].reason == "preferred_ambiguous"
    assert admin_session.execute(select(HrPreferredRecord)).first() is not None


async def test_preference_invalid_at_sync_time_falls_back_and_warns(admin_session):
    _holding(admin_session)
    _owner(admin_session, "first@x.example")  # the preferred record's email is now taken
    _prefer(admin_session, "p-1", "t_person_id", "T1")
    run = await _run(admin_session, DUP)
    assert run.conflict_count >= 1
    assert _soldier(admin_session, "p-1").full_name == "Second"
    assert any(c.reason == "preferred_invalid" for c in _conflicts(admin_session, "p-1"))
    assert admin_session.execute(select(HrPreferredRecord)).first() is not None


async def test_preference_ignored_but_kept_when_feed_has_no_duplicate(admin_session):
    _holding(admin_session)
    _prefer(admin_session, "p-5", "t_person_id", "T1")
    run = await _run(admin_session, [_rec("p-5", fullName="Only", t_personID="T2", mail="only@x.example")])
    assert run.conflict_count == 0
    assert _soldier(admin_session, "p-5").full_name == "Only"
    assert admin_session.execute(select(HrPreferredRecord)).first() is not None
