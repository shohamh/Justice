from __future__ import annotations

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import event as sqlalchemy_event, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db.models import AuditLog, RangeEvent, RangeEventStatus, RangeType
from app.range_attendance_worker import _auto_mark_present_for_elapsed_events
from app.routes.ranges import get_range_event, list_range_events
from app.services.ranges import (
    RangeValidationError,
    add_range_assignment,
    create_range_event,
    mark_past_range_events_completed,
    update_range_event,
)
from app.services.settings_loader import apply_settings
from app import range_attendance_worker
from tests.helpers import create_node, create_range_location, create_soldier


def _event(session: Session, *, event_date: date, status: RangeEventStatus = RangeEventStatus.planned) -> RangeEvent:
    node = create_node(session, level="branch", name=f"range-status-{event_date}-{status.value}")
    event = create_range_event(
        session,
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        event_date=event_date,
        range_location_id=create_range_location(session, name=f"range-status-{event_date}-{status.value}").id,
        required_count=1,
    )
    event.status = status
    session.commit()
    return event


def test_mark_past_range_events_completed_only_transitions_past_planned_events(app_session: Session) -> None:
    today = date(2026, 8, 15)
    past_planned = _event(app_session, event_date=today - timedelta(days=1))
    today_planned = _event(app_session, event_date=today)
    future_planned = _event(app_session, event_date=today + timedelta(days=1))
    cancelled_past = _event(
        app_session, event_date=today - timedelta(days=1), status=RangeEventStatus.cancelled
    )

    changed = mark_past_range_events_completed(app_session, today=today)

    assert changed == 1
    assert past_planned.status == RangeEventStatus.completed
    assert today_planned.status == RangeEventStatus.planned
    assert future_planned.status == RangeEventStatus.planned
    assert cancelled_past.status == RangeEventStatus.cancelled


def test_concurrent_elapsed_transitions_change_and_audit_each_event_once(
    app_engine, app_session: Session
) -> None:
    today = date(2026, 8, 15)
    event = _event(app_session, event_date=today - timedelta(days=1))
    readers = Barrier(2)

    def synchronize_candidate_reads(
        _conn, _cursor, statement: str, _parameters, _context, _executemany
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT") and "FROM range_events" in statement:
            readers.wait(timeout=5)

    sqlalchemy_event.listen(app_engine, "before_cursor_execute", synchronize_candidate_reads)
    try:
        SessionLocal = sessionmaker(bind=app_engine, expire_on_commit=False)

        def transition() -> int:
            with SessionLocal() as session:
                changed = mark_past_range_events_completed(session, today=today)
                session.commit()
                return changed

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: transition(), range(2)))
    finally:
        sqlalchemy_event.remove(app_engine, "before_cursor_execute", synchronize_candidate_reads)

    app_session.expire_all()
    assert sorted(results) == [0, 1]
    assert app_session.get(RangeEvent, event.id).status == RangeEventStatus.completed
    audits = app_session.execute(
        select(AuditLog).where(
            AuditLog.action == "range_event.complete",
            AuditLog.entity_id == event.id,
        )
    ).scalars().all()
    assert len(audits) == 1


def test_range_routes_return_past_event_as_completed_and_second_transition_is_a_no_op(
    app_session: Session,
) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    admin = create_soldier(app_session, personal_number="range-status-admin", role="admin")
    past_event = _event(app_session, event_date=date.today() - timedelta(days=1))

    listed = list_range_events(session=app_session, user=admin, node_id=str(past_event.hierarchy_node_id))
    detailed = get_range_event(session=app_session, user=admin, event_id=past_event.id)

    assert listed[0].status == RangeEventStatus.completed
    assert detailed.status == RangeEventStatus.completed
    assert mark_past_range_events_completed(app_session) == 0


def test_completed_event_preserves_update_and_assignment_guards(app_session: Session) -> None:
    today = date(2026, 8, 15)
    event = _event(app_session, event_date=today - timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="range-status-soldier")

    assert mark_past_range_events_completed(app_session, today=today) == 1

    with pytest.raises(RangeValidationError, match="event_not_planned"):
        update_range_event(app_session, event=event, notes="too late")
    with pytest.raises(RangeValidationError, match="event_not_planned"):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_worker_commits_completed_range_event(app_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    event = _event(app_session, event_date=date.today() - timedelta(days=1))
    monkeypatch.setattr(range_attendance_worker, "session_scope", lambda: nullcontext(app_session))
    monkeypatch.setattr(range_attendance_worker, "auto_mark_present_for_elapsed_events", lambda session: 0)

    _auto_mark_present_for_elapsed_events()

    app_session.expire(event)
    assert event.status == RangeEventStatus.completed


@pytest.mark.parametrize("route", ["list", "detail"])
def test_forbidden_range_route_does_not_transition_elapsed_events(
    app_session: Session, route: str
) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    unauthorized_user = create_soldier(app_session, personal_number=f"range-status-forbidden-{route}")
    event = _event(app_session, event_date=date.today() - timedelta(days=1))

    with pytest.raises(HTTPException) as exc_info:
        if route == "list":
            list_range_events(
                session=app_session,
                user=unauthorized_user,
                node_id=str(event.hierarchy_node_id),
            )
        else:
            get_range_event(session=app_session, user=unauthorized_user, event_id=event.id)

    assert exc_info.value.status_code == 403
    assert event.status == RangeEventStatus.planned
