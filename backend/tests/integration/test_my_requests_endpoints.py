"""Integration tests for the soldier-facing "my requests" endpoints.

Covers the requests-page contract: per-type history views scoped to the
authenticated soldier, and the unseen-count / mark-seen badge pair.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone


from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    HierarchyTransferRequest,
    PersonalConstraint,
    RangeExcusalRequest,
    SoldierEnrollmentRequest,
    SoldierFieldUpdate,
)
from sqlalchemy import update
from tests.helpers import (
    auth_headers,
    create_node,
    create_range_assignment,
    create_range_event,
    create_range_location,
    create_soldier,
)


def _seed_constraint(
    session: Session,
    soldier_id,
    *,
    decided_at: datetime | None,
    status: str = "approved",
    decided_by=None,
) -> PersonalConstraint:
    c = PersonalConstraint(
        soldier_id=soldier_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason="בקשת בדיקה",
        status=status,
        decided_at=decided_at,
        decided_by=decided_by,
    )
    session.add(c)
    session.commit()
    return c


def _seed_transfer(
    session: Session,
    soldier,
    to_node_id,
    *,
    status: str = "pending",
) -> HierarchyTransferRequest:
    req = HierarchyTransferRequest(
        soldier_id=soldier.id,
        to_node_id=to_node_id,
        requested_by=soldier.id,
        status=status,
    )
    session.add(req)
    session.flush()
    if status in ("approved", "rejected"):
        # Production writes exactly this audit entry at decision time; the
        # endpoints derive the transfer's decided_at from it.
        write_audit(
            session,
            actor_id=soldier.id,
            action=f"hierarchy_transfer.{status}",
            entity_type="hierarchy_transfer_request",
            entity_id=req.id,
        )
    session.commit()
    return req


# ── Hierarchy transfers ──


def test_hierarchy_transfers_returns_only_own_rows(client: TestClient, admin_session: Session):
    mine = create_soldier(admin_session, personal_number="7700101")
    other = create_soldier(admin_session, personal_number="7700102")
    node_a = create_node(admin_session, level="department", name="ht-node-a")
    node_b = create_node(admin_session, level="branch", name="ht-node-b", parent=node_a)

    own_req = _seed_transfer(admin_session, mine, node_b.id)
    _seed_transfer(admin_session, other, node_a.id)

    r = client.get("/api/me/hierarchy-transfers", headers=auth_headers(mine))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["id"] for row in rows] == [str(own_req.id)]
    row = rows[0]
    assert row["status"] == "pending"
    assert row["decided_at"] is None
    assert row["decision_note"] is None
    assert row["from_node"] is None
    assert row["to_node"] == {"id": str(node_b.id), "name": "ht-node-b"}
    assert datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))


def test_hierarchy_transfers_reports_decided_at_and_from_node(
    client: TestClient, admin_session: Session
):
    s = create_soldier(admin_session, personal_number="7700110")
    node_a = create_node(admin_session, level="department", name="ht-from")
    node_b = create_node(admin_session, level="department", name="ht-to")

    req = HierarchyTransferRequest(
        soldier_id=s.id,
        to_node_id=node_b.id,
        requested_by=s.id,
        from_node_id=node_a.id,
        status="approved",
        decision_note="עבר למדור אחר",
    )
    admin_session.add(req)
    admin_session.flush()
    write_audit(
        admin_session,
        actor_id=s.id,
        action="hierarchy_transfer.approve",
        entity_type="hierarchy_transfer_request",
        entity_id=req.id,
    )
    admin_session.commit()

    r = client.get("/api/me/hierarchy-transfers", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["status"] == "approved"
    assert row["decision_note"] == "עבר למדור אחר"
    assert row["from_node"] == {"id": str(node_a.id), "name": "ht-from"}
    assert row["to_node"] == {"id": str(node_b.id), "name": "ht-to"}
    assert row["decided_at"] is not None


def test_hierarchy_transfers_empty_list(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7700111")
    r = client.get("/api/me/hierarchy-transfers", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    assert r.json() == []


# ── Enrollment ──


def test_enrollment_returns_null_when_none(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7700201")
    r = client.get("/api/me/enrollment", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    assert r.json() == {"request": None}


def test_enrollment_excludes_other_soldiers_requests(client: TestClient, admin_session: Session):
    mine = create_soldier(admin_session, personal_number="7700202")
    other = create_soldier(admin_session, personal_number="7700203")
    node = create_node(admin_session, level="department", name="enr-node")

    own_req = SoldierEnrollmentRequest(
        soldier_id=mine.id,
        requested_node_id=node.id,
        status="approved",
        decided_by=other.id,
        decided_at=datetime.now(timezone.utc),
        decision_note="ברוך הבא",
    )
    foreign = SoldierEnrollmentRequest(soldier_id=other.id, requested_node_id=node.id)
    admin_session.add_all([own_req, foreign])
    admin_session.commit()

    r = client.get("/api/me/enrollment", headers=auth_headers(mine))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request"]["id"] == str(own_req.id)
    assert body["request"]["status"] == "approved"
    assert body["request"]["requested_node_name"] == "enr-node"
    assert body["request"]["decision_note"] == "ברוך הבא"
    assert body["request"]["decided_at"] is not None

    r2 = client.get("/api/me/enrollment", headers=auth_headers(other))
    assert r2.json()["request"]["id"] == str(foreign.id)


# ── Range excusal requests ──


def test_range_excusals_return_only_own_rows_with_event_info(
    client: TestClient, admin_session: Session
):
    mine = create_soldier(admin_session, personal_number="7700301")
    other = create_soldier(admin_session, personal_number="7700302")
    node = create_node(admin_session, level="department", name="re-node")
    location = create_range_location(admin_session, name="מטווח בודק")
    event = create_range_event(
        admin_session, hierarchy_node=node, range_location=location, range_type="live"
    )

    own_req = RangeExcusalRequest(
        reason="חופשה מאושרת", requested_by=mine.id, range_event_id=event.id, range_assignment_id=None
    )
    foreign = RangeExcusalRequest(
        reason="של אחר", requested_by=other.id, range_event_id=event.id, range_assignment_id=None
    )
    admin_session.add_all([own_req, foreign])
    admin_session.commit()

    r = client.get("/api/me/range-excusal-requests", headers=auth_headers(mine))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["id"] for row in rows] == [str(own_req.id)]
    row = rows[0]
    assert row["status"] == "pending"
    assert row["reason"] == "חופשה מאושרת"
    assert row["range_date"] == event.date.isoformat()
    assert row["range_type"] == "live"
    assert row["range_location_name"] == "מטווח בודק"
    assert row["decided_at"] is None
    assert datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))


def test_range_excusals_resolve_event_through_assignment_fallback(
    client: TestClient, admin_session: Session
):
    """A pending excusal still linked only through its range assignment must
    resolve date/type/location via that assignment."""
    s = create_soldier(admin_session, personal_number="7700311")
    node = create_node(admin_session, level="department", name="re-fb-node")
    location = create_range_location(admin_session, name="מטווח פלבק")
    event = create_range_event(
        admin_session,
        hierarchy_node=node,
        range_location=location,
        range_type="laser",
        event_date=date(2026, 10, 5),
    )
    assignment = create_range_assignment(admin_session, range_event=event, soldier=s)

    req = RangeExcusalRequest(reason="מיון רפואי", requested_by=s.id, range_assignment_id=assignment.id)
    admin_session.add(req)
    admin_session.commit()

    r = client.get("/api/me/range-excusal-requests", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["range_date"] == "2026-10-05"
    assert row["range_type"] == "laser"
    assert row["range_location_name"] == "מטווח פלבק"


def test_range_excusals_empty_list(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7700321")
    r = client.get("/api/me/range-excusal-requests", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    assert r.json() == []


# ── Unseen count / mark-seen ──


def test_unseen_count_zero_without_stored_last_seen(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7700401")
    # A decision already exists, but the soldier never opened the page.
    _seed_constraint(admin_session, s.id, decided_at=datetime.now(timezone.utc))

    r = client.get("/api/me/requests/unseen-count", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 0}


def test_unseen_count_counts_decided_constraint_after_mark_seen_flow(
    client: TestClient, admin_session: Session
):
    s = create_soldier(admin_session, personal_number="7700402")

    r = client.post("/api/me/requests/mark-seen", headers=auth_headers(s))
    assert r.status_code == 204, r.text
    visited_at = datetime.now(timezone.utc)

    # Decided before the visit above → already seen.
    _seed_constraint(admin_session, s.id, decided_at=visited_at - timedelta(minutes=5))
    # Pending constraint carries no decision and must never count.
    _seed_constraint(admin_session, s.id, decided_at=None, status="pending_commander")
    # Another soldier's fresh decision belongs to their badge, not ours.
    stranger = create_soldier(admin_session, personal_number="7700403")
    _seed_constraint(admin_session, stranger.id, decided_at=datetime.now(timezone.utc))

    r = client.get("/api/me/requests/unseen-count", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 0}

    # Decided after the stored last-seen → counted exactly once.
    _seed_constraint(admin_session, s.id, decided_at=datetime.now(timezone.utc))

    r = client.get("/api/me/requests/unseen-count", headers=auth_headers(s))
    assert r.json() == {"count": 1}

    # Re-opening the page resets the badge to zero.
    r = client.post("/api/me/requests/mark-seen", headers=auth_headers(s))
    assert r.status_code == 204, r.text
    r = client.get("/api/me/requests/unseen-count", headers=auth_headers(s))
    assert r.json() == {"count": 0}


def test_mark_seen_requires_auth(client: TestClient):
    r = client.post("/api/me/requests/mark-seen")
    assert r.status_code == 401


# ── Requests-page metadata (waiting_on / decided_by / requested_at / updated_at) ──


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _backdate(session: Session, model, row_id, column: str = "created_at", *, minutes: int = 60):
    session.execute(
        update(model)
        .where(model.id == row_id)
        .values({column: datetime.now(timezone.utc) - timedelta(minutes=minutes)})
    )
    session.commit()


def test_pending_constraint_waiting_on_resolves_nearest_commander(
    client: TestClient, admin_session: Session
):
    cmd = create_soldier(admin_session, personal_number="7705001", full_name="מפקד אילוץ")
    node = create_node(admin_session, level="department", name="meta-node", commander_id=cmd.id)
    s = create_soldier(admin_session, personal_number="7705002", hierarchy_node_id=node.id)
    _seed_constraint(admin_session, s.id, decided_at=None, status="pending_commander")

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["status"] == "pending_commander"
    assert row["waiting_on"] == {
        "kind": "commander",
        "soldier_id": str(cmd.id),
        "name": "מפקד אילוץ",
    }
    assert _iso(row["requested_at"]) is not None
    assert _iso(row["updated_at"]) >= _iso(row["created_at"])


def test_pending_duty_manager_constraint_waits_on_duty_manager(
    client: TestClient, admin_session: Session
):
    node = create_node(admin_session, level="department", name="dm-meta-node")
    s = create_soldier(admin_session, personal_number="7705011", hierarchy_node_id=node.id)
    dm = create_soldier(
        admin_session, personal_number="7705012", role="duty_manager",
        hierarchy_node_id=node.id, full_name="אחראי סבלני",
    )
    _seed_constraint(admin_session, s.id, decided_at=None, status="pending_duty_manager")

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["waiting_on"] == {
        "kind": "duty_manager",
        "soldier_id": str(dm.id),
        "name": "אחראי סבלני",
    }


def test_decided_constraint_has_null_waiting_on(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="decided-node")
    s = create_soldier(admin_session, personal_number="7705021", hierarchy_node_id=node.id)
    _seed_constraint(admin_session, s.id, decided_at=datetime.now(timezone.utc), status="approved")

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["waiting_on"] is None


def test_rejected_constraint_decided_by_carries_name(
    client: TestClient, admin_session: Session
):
    cmd = create_soldier(admin_session, personal_number="7705031", full_name="מפקד מחליט")
    node = create_node(admin_session, level="department", name="reject-node", commander_id=cmd.id)
    s = create_soldier(admin_session, personal_number="7705032", hierarchy_node_id=node.id)
    _seed_constraint(
        admin_session, s.id,
        decided_at=datetime.now(timezone.utc), status="rejected", decided_by=cmd.id,
    )

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["waiting_on"] is None
    assert row["decided_by"] == {"soldier_id": str(cmd.id), "name": "מפקד מחליט"}
    assert row["commander_approved_by"] is None


def test_constraint_reports_intermediate_commander_approver(
    client: TestClient, admin_session: Session
):
    cmd = create_soldier(admin_session, personal_number="7705040", full_name="מפקד ביניים")
    node = create_node(admin_session, level="department", name="two-step-node")
    s = create_soldier(admin_session, personal_number="7705041", hierarchy_node_id=node.id)
    dm = create_soldier(
        admin_session, personal_number="7705042", role="duty_manager",
        hierarchy_node_id=node.id, full_name="אחראי סופי",
    )
    c = _seed_constraint(
        admin_session, s.id,
        decided_at=datetime.now(timezone.utc), status="approved", decided_by=dm.id,
    )
    admin_session.execute(
        update(PersonalConstraint).where(PersonalConstraint.id == c.id)
        .values(commander_approved_by=cmd.id)
    )
    admin_session.commit()

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["waiting_on"] is None  # approved → nobody waiting anymore
    assert row["decided_by"] == {"soldier_id": str(dm.id), "name": "אחראי סופי"}
    assert row["commander_approved_by"] == {"soldier_id": str(cmd.id), "name": "מפקד ביניים"}


def test_updated_and_decided_metadata_across_request_types(
    client: TestClient, admin_session: Session
):
    s = create_soldier(admin_session, personal_number="7705100")
    other = create_soldier(admin_session, personal_number="7705101", full_name="מחליט אחר")
    cmd = create_soldier(admin_session, personal_number="7705102", full_name="מאשר העברה")

    # Hierarchy transfer: decision derived from the audit entry's actor + time.
    req = HierarchyTransferRequest(
        soldier_id=s.id, to_node_id=create_node(admin_session, level="branch", name="meta-ht").id,
        requested_by=s.id, status="approved", decision_note="אושר",
    )
    admin_session.add(req)
    admin_session.flush()
    write_audit(
        admin_session, actor_id=cmd.id, action="hierarchy_transfer.approve",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
    )
    admin_session.commit()
    _backdate(admin_session, HierarchyTransferRequest, req.id)

    r = client.get("/api/me/hierarchy-transfers", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (ht,) = r.json()
    assert ht["requested_at"] == ht["created_at"]
    assert _iso(ht["updated_at"]) > _iso(ht["created_at"])
    assert ht["decided_by"] == {"soldier_id": str(cmd.id), "name": "מאשר העברה"}
    assert ht["waiting_on"] is None
    assert ht["commander_approved_by"] is None

    # Enrollment: decided columns joined to names server-side.
    enr = SoldierEnrollmentRequest(
        soldier_id=s.id,
        requested_node_id=create_node(admin_session, level="branch", name="meta-enr").id,
        status="approved", decided_by=other.id, decided_at=datetime.now(timezone.utc),
    )
    admin_session.add(enr)
    admin_session.commit()
    _backdate(admin_session, SoldierEnrollmentRequest, enr.id)

    r = client.get("/api/me/enrollment", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    body = r.json()["request"]
    assert body["decided_by"] == {"soldier_id": str(other.id), "name": "מחליט אחר"}
    assert _iso(body["updated_at"]) >= _iso(body["created_at"])

    # Range excusal: requested_at is the native creation column.
    exc = RangeExcusalRequest(
        reason="מטעמים רפואיים", requested_by=s.id, range_assignment_id=None,
        decided_by=other.id, decided_at=datetime.now(timezone.utc), decision_note=None,
    )
    admin_session.add(exc)
    admin_session.flush()
    admin_session.execute(
        update(RangeExcusalRequest).where(RangeExcusalRequest.id == exc.id)
        .values(requested_at=datetime.now(timezone.utc) - timedelta(days=2))
    )
    admin_session.commit()

    r = client.get("/api/me/range-excusal-requests", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (re_row,) = [row for row in r.json() if row["id"] == str(exc.id)]
    assert re_row["requested_at"] == re_row["created_at"]
    assert _iso(re_row["updated_at"]) > _iso(re_row["created_at"])
    assert re_row["decided_by"]["soldier_id"] == str(other.id)


def test_exemption_own_list_carries_decision_metadata(
    client: TestClient, admin_session: Session
):
    from app.db.models import ExemptionRequest, ExemptionType, Notification, NotificationType

    node = create_node(admin_session, level="department", name="exm-meta-node")
    s = create_soldier(admin_session, personal_number="7705200", hierarchy_node_id=node.id)
    cmd = create_soldier(admin_session, personal_number="7705201", full_name="מפקד פטור")
    dm = create_soldier(
        admin_session, personal_number="7705202", role="duty_manager",
        hierarchy_node_id=node.id, full_name="אחראי פטור",
    )
    et = ExemptionType(name=f"פטור בדיקה {uuid.uuid4().hex[:6]}")
    admin_session.add(et)
    admin_session.flush()

    pending_req = ExemptionRequest(soldier_id=s.id, exemption_type_id=et.id, status="pending_duty_manager")
    decided = ExemptionRequest(
        soldier_id=s.id, exemption_type_id=et.id, status="rejected",
        decided_by=dm.id, commander_approved_by=cmd.id, decision_note="לא",
    )
    admin_session.add_all([pending_req, decided])
    admin_session.flush()
    admin_session.add(Notification(
        soldier_id=s.id, title="נדחה", type=NotificationType.exemption_rejected,
        reference_type="exemption_request", reference_id=decided.id,
    ))
    admin_session.commit()
    _backdate(admin_session, ExemptionRequest, decided.id, minutes=24 * 60)

    r = client.get("/api/me/exemption-requests", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    rows = {row["status"]: row for row in r.json()}

    waiting = rows["pending_duty_manager"]
    assert waiting["waiting_on"]["kind"] == "duty_manager"
    assert waiting["decided_by"] is None
    assert waiting["commander_approved_by"] is None

    rejected = rows["rejected"]
    assert rejected["waiting_on"] is None
    assert rejected["decided_by"] == {"soldier_id": str(dm.id), "name": "אחראי פטור"}
    assert rejected["commander_approved_by"] == {"soldier_id": str(cmd.id), "name": "מפקד פטור"}
    # No decided_at column — updated_at derives from the requester notification.
    assert _iso(rejected["updated_at"]) > _iso(rejected["created_at"])


def test_field_update_history_includes_new_fields(
    client: TestClient, admin_session: Session
):
    from app.services.soldiers import approve_field_update, submit_field_update

    node = create_node(admin_session, level="department", name="fu-meta-node")
    s = create_soldier(admin_session, personal_number="7705300", hierarchy_node_id=node.id)
    cmd = create_soldier(admin_session, personal_number="7705301", full_name="מפקד שדה")

    upd = submit_field_update(
        admin_session, soldier_id=s.id, field_name="phone",
        new_value="052-0000001", actor_id=s.id,
    )
    approve_field_update(admin_session, update=upd, actor_id=cmd.id, decision_note="אושר")
    admin_session.commit()
    _backdate(admin_session, SoldierFieldUpdate, upd.id)

    r = client.get(f"/api/soldiers/{s.id}/field-updates", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert row["field_name"] == "phone"
    assert row["status"] == "approved"
    assert row["waiting_on"] is None
    assert row["commander_approved_by"] is None
    assert row["decided_by"] == {"soldier_id": str(cmd.id), "name": "מפקד שדה"}
    assert row["requested_at"] == row["created_at"]
    assert _iso(row["updated_at"]) > _iso(row["created_at"])
