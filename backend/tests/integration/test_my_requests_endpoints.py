"""Integration tests for the soldier-facing "my requests" endpoints.

Covers the requests-page contract: per-type history views scoped to the
authenticated soldier, and the unseen-count / mark-seen badge pair.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    HierarchyTransferRequest,
    PersonalConstraint,
    RangeExcusalRequest,
    SoldierEnrollmentRequest,
)
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
) -> PersonalConstraint:
    c = PersonalConstraint(
        soldier_id=soldier_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason="בקשת בדיקה",
        status=status,
        decided_at=decided_at,
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
