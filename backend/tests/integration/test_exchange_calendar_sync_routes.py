"""Admin Exchange calendar status and asynchronous retry HTTP contract."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    ExchangeCalendarOutbox,
    ExchangeCalendarSyncAttempt,
    ExchangeCalendarSyncItem,
    ExchangeCalendarWorkerState,
)
from tests.helpers import (
    auth_headers,
    create_node,
    create_range_assignment,
    create_range_event,
    create_range_location,
    create_soldier,
)

BASE = "/api/admin/exchange-calendar-sync"


@pytest.fixture(autouse=True)
def clean_exchange_rows(admin_engine):
    def clear():
        with Session(admin_engine) as session:
            for model in (ExchangeCalendarSyncAttempt, ExchangeCalendarOutbox,
                          ExchangeCalendarSyncItem, ExchangeCalendarWorkerState):
                session.execute(delete(model))
            session.commit()

    clear()
    yield
    clear()


def _admin(session: Session):
    person = create_soldier(session, personal_number=f"exchange-{uuid4().hex[:10]}", role="admin")
    session.commit()
    return person


def _item(session: Session, *, status: str, source_type: str = "duty_shift", source_date: date | None = None):
    item = ExchangeCalendarSyncItem(
        source_type=source_type, source_id=uuid4(), source_date=source_date,
        status=status,
    )
    session.add(item)
    session.commit()
    return item


def test_all_exchange_status_routes_require_admin(client: TestClient, admin_session: Session):
    person = create_soldier(admin_session, personal_number="exchange-non-admin")
    admin_session.commit()
    headers = auth_headers(person)
    source_id = uuid4()
    assert client.get(f"{BASE}/summary", headers=headers).status_code == 403
    assert client.get(f"{BASE}/events", headers=headers).status_code == 403
    assert client.post(f"{BASE}/events/duty_shift/{source_id}/retry", headers=headers).status_code == 403


def test_empty_summary_separates_worker_and_exchange_state(client: TestClient, admin_session: Session):
    response = client.get(f"{BASE}/summary", headers=auth_headers(_admin(admin_session)))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"] == {"eligible": 0, "queued": 0, "in_progress": 0, "synced": 0,
                              "partial": 0, "retry_wait": 0, "failed": 0}
    assert body["recent"] == {"created": 0, "updated": 0, "cancelled": 0,
                              "partial": 0, "failed": 0}
    assert body["worker_heartbeat_at"] is None
    assert body["exchange_reachable"] is None


def test_summary_counts_status_history_and_shared_outage(client: TestClient, admin_session: Session):
    now = datetime.now(UTC)
    item = _item(admin_session, status="partial", source_date=now.date() + timedelta(days=1))
    _item(admin_session, status="failed", source_date=now.date() + timedelta(days=2))
    admin_session.add(ExchangeCalendarSyncAttempt(sync_item_id=item.id, outcome="partial"))
    admin_session.add(ExchangeCalendarSyncAttempt(sync_item_id=item.id, outcome="created"))
    admin_session.add(ExchangeCalendarWorkerState(
        id=1, heartbeat_at=now, last_probe_at=now - timedelta(minutes=3),
        exchange_reachable=False, last_connection_attempt_at=now - timedelta(minutes=3),
        last_successful_contact_at=now - timedelta(hours=1),
        latest_connection_error="password=secret <soap>private</soap>",
        global_backoff_until=now + timedelta(minutes=5),
    ))
    admin_session.commit()
    response = client.get(f"{BASE}/summary", headers=auth_headers(_admin(admin_session)))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["partial"] == 1
    assert body["counts"]["failed"] == 1
    assert body["recent"]["partial"] == 1
    assert body["recent"]["created"] == 1
    assert body["worker_heartbeat_at"] is not None
    assert body["exchange_reachable"] is False
    assert body["global_backoff_until"] is not None
    assert "secret" not in str(body)
    assert "soap" not in str(body).lower()


@pytest.mark.parametrize(
    ("stored_error", "expected_category", "expected_message"),
    [
        ("Exchange probe failed", "exchange_unavailable", "Exchange probe failed."),
        ("Exchange request failed", "exchange_unavailable", "Exchange is unavailable. The worker will retry."),
        ("Exchange is busy", "exchange_busy", "Exchange is busy. The worker will retry after backoff."),
    ],
)
def test_summary_preserves_only_allow_listed_exchange_diagnostics(
    client: TestClient, admin_session: Session,
    stored_error: str, expected_category: str, expected_message: str,
):
    admin_session.add(ExchangeCalendarWorkerState(
        id=1, exchange_reachable=False, latest_connection_error=stored_error,
    ))
    admin_session.commit()
    response = client.get(f"{BASE}/summary", headers=auth_headers(_admin(admin_session)))
    assert response.status_code == 200, response.text
    assert response.json()["latest_connection_error_category"] == expected_category
    assert response.json()["latest_connection_error"] == expected_message


def test_summary_does_not_echo_unrecognized_connection_error(
    client: TestClient, admin_session: Session,
):
    raw_error = "Exchange probe failed: password=do-not-leak"
    admin_session.add(ExchangeCalendarWorkerState(
        id=1, exchange_reachable=False, latest_connection_error=raw_error,
    ))
    admin_session.commit()

    response = client.get(f"{BASE}/summary", headers=auth_headers(_admin(admin_session)))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["latest_connection_error_category"] is None
    assert body["latest_connection_error"] == "Calendar sync failed."
    assert raw_error not in response.text
    assert "do-not-leak" not in response.text


def test_summary_counts_upcoming_queued_source_before_worker_sets_its_date(
    client: TestClient, admin_session: Session,
):
    node = create_node(admin_session, level="team", name="Exchange queued event")
    location = create_range_location(admin_session, name="Range 8")
    event = create_range_event(
        admin_session, hierarchy_node=node, range_location=location,
        event_date=datetime.now(UTC).date() + timedelta(days=2), required_count=1,
    )
    admin_session.add(ExchangeCalendarSyncItem(
        source_type="range_event", source_id=event.id, status="queued", source_date=None,
    ))
    admin_session.commit()
    admin = _admin(admin_session)
    response = client.get(f"{BASE}/summary", headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["eligible"] == 1
    assert response.json()["counts"]["queued"] == 1
    events = client.get(f"{BASE}/events", headers=auth_headers(admin))
    assert events.status_code == 200, events.text
    assert events.json()["items"][0]["source_date"] == event.date.isoformat()


def test_events_are_paginated_and_never_expose_exchange_ids_or_raw_errors(
    client: TestClient, admin_session: Session,
):
    now = datetime.now(UTC)
    first = _item(admin_session, status="failed", source_date=now.date())
    _item(admin_session, status="synced", source_date=now.date() + timedelta(days=1))
    first.exchange_item_id = "private-exchange-item-id"
    first.current_error_category = "auth_failure"
    first.current_error = "password=secret <soap>private</soap>"
    first.last_attempt_at = now
    admin_session.add(ExchangeCalendarSyncAttempt(
        sync_item_id=first.id, outcome="failed", error_category="auth_failure",
        error_message="password=secret <soap>private</soap>",
    ))
    admin_session.commit()
    headers = auth_headers(_admin(admin_session))
    response = client.get(f"{BASE}/events", params={"limit": 1, "offset": 0}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["source_type"] in {"duty_shift", "range_event", "duty_assignment"}
    assert "secret" not in str(body)
    assert "soap" not in str(body).lower()
    assert "private-exchange-item-id" not in str(body)
    assert client.get(f"{BASE}/events", params={"limit": 101}, headers=headers).status_code == 422
    assert client.get(f"{BASE}/events", params={"limit": 1, "offset": 1}, headers=headers).json()["items"][0]["source_id"] != body["items"][0]["source_id"]


@pytest.mark.parametrize("aged_out", [False, True])
def test_events_derive_current_missing_optional_attendee_without_sharing_event_notes(
    client: TestClient, admin_session: Session, aged_out: bool,
):
    admin = _admin(admin_session)
    node = create_node(admin_session, level="team", name="Exchange route test")
    location = create_range_location(admin_session, name="Range 7")
    event_date = datetime.now(UTC).date() + timedelta(days=-2 if aged_out else 1)
    event = create_range_event(
        admin_session, hierarchy_node=node, range_location=location,
        event_date=event_date, required_count=1,
    )
    event.notes = "private operational note"
    invited = create_soldier(admin_session, personal_number="exchange-invited")
    invited.email = "invited@example.test"
    optional = create_soldier(
        admin_session, personal_number="exchange-optional", full_name="Optional attendee",
    )
    event.responsible_duty_manager_id = optional.id
    create_range_assignment(admin_session, range_event=event, soldier=invited)
    admin_session.add(ExchangeCalendarSyncItem(
        source_type="range_event", source_id=event.id, source_date=event_date,
        status="partial", last_success_at=datetime.now(UTC),
        exchange_item_id="private-exchange-id" if aged_out else None,
    ))
    admin_session.commit()

    response = client.get(f"{BASE}/events", headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["status"] == "partial"
    assert item["last_success_at"] is not None
    assert item["current_projection_problems"] == [{
        "code": "missing_email", "message": "An invited person has no usable email address.",
        "attendee": {"name": "Optional attendee", "role": "responsible_duty_manager"},
    }]
    assert "exchange-optional" not in response.text
    assert "private operational note" not in response.text
    assert "private-exchange-id" not in response.text


def test_events_report_resolved_contact_without_usable_email(client: TestClient, admin_session: Session):
    admin = _admin(admin_session)
    node = create_node(admin_session, level="team", name="Exchange contact test")
    location = create_range_location(admin_session, name="Range 9")
    event_date = datetime.now(UTC).date() + timedelta(days=1)
    event = create_range_event(
        admin_session, hierarchy_node=node, range_location=location,
        event_date=event_date, required_count=1,
    )
    event.contact_name = "Range Contact"
    event.contact_phone = "555-0101"
    create_soldier(
        admin_session, personal_number="exchange-contact", full_name="Range Contact",
    )
    admin_session.add(ExchangeCalendarSyncItem(
        source_type="range_event", source_id=event.id, source_date=event_date,
        status="partial",
    ))
    admin_session.commit()

    response = client.get(f"{BASE}/events", headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["current_projection_problems"] == [{
        "code": "missing_email", "message": "An invited person has no usable email address.",
        "attendee": {"name": "Range Contact", "role": "contact"},
    }]
    assert "exchange-contact" not in response.text
    assert "555-0101" not in response.text


def test_retry_only_queues_urgent_source_work(client: TestClient, admin_session: Session):
    item = _item(admin_session, status="failed")
    headers = auth_headers(_admin(admin_session))
    response = client.post(f"{BASE}/events/duty_shift/{item.source_id}/retry", headers=headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "accepted"
    admin_session.expire_all()
    jobs = admin_session.scalars(select(ExchangeCalendarOutbox).where(
        ExchangeCalendarOutbox.source_type == "duty_shift",
        ExchangeCalendarOutbox.source_id == item.source_id,
    )).all()
    assert len(jobs) == 1
    assert jobs[0].status == "queued"
    assert jobs[0].priority == 200
    assert admin_session.get(ExchangeCalendarSyncItem, item.id).status == "queued"
    assert client.post(f"{BASE}/events/duty_shift/{uuid4()}/retry", headers=headers).status_code == 404
