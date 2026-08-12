from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.auth.jwt_tokens import issue_access_token
from app.auth.password import hash_password
from app.db.models import DutyLocation, DutyManagerScope, HierarchyNode, RangeAssignment, RangeEvent, RangeLocation, Soldier


def create_node(
    session: Session,
    *,
    level: str,
    name: str,
    parent: HierarchyNode | None = None,
    commander_id: uuid.UUID | None = None,
) -> HierarchyNode:
    """Insert a node and set its materialized path_ids. Test-only shortcut that
    bypasses the service-layer validation (so tests can build arbitrary trees fast)."""
    node = HierarchyNode(
        level=level,
        name=name,
        parent_id=parent.id if parent else None,
        commander_id=commander_id,
        path_ids=[],
    )
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = [*parent.path_ids, node.id] if parent else [node.id]
    session.flush()
    return node


def create_soldier(
    session: Session,
    *,
    personal_number: str,
    role: str = "soldier",
    password: str = "password-1234",
    hierarchy_node_id: uuid.UUID | None = None,
    must_change_password: bool = False,
    full_name: str | None = None,
) -> Soldier:
    s = Soldier(
        personal_number=personal_number,
        full_name=full_name or f"Test {personal_number}",
        password_hash=hash_password(password),
        role=role,
        hierarchy_node_id=hierarchy_node_id,
        must_change_password=must_change_password,
    )
    session.add(s)
    session.flush()
    # For duty_managers: automatically create a DutyManagerScope entry
    # so scope_root_ids (which reads DutyManagerScope) works out-of-the-box in tests.
    if role == "duty_manager" and hierarchy_node_id is not None:
        session.add(DutyManagerScope(duty_manager_id=s.id, hierarchy_node_id=hierarchy_node_id))
    session.commit()
    session.refresh(s)
    return s


def create_duty_location(session: Session, *, name: str = "מיקום בדיקה") -> DutyLocation:
    location = DutyLocation(name=name)
    session.add(location)
    session.flush()
    return location


def create_range_location(session: Session, *, name: str = "מיקום מטווח בדיקה") -> RangeLocation:
    location = RangeLocation(name=name)
    session.add(location)
    session.flush()
    return location


def create_range_event(
    session: Session, *, hierarchy_node, range_location, range_type: str = "live",
    event_date: date | None = None, required_count: int = 5, reserve_count: int = 0,
    status: str = "planned",
) -> RangeEvent:
    event = RangeEvent(
        hierarchy_node_id=hierarchy_node.id,
        range_type=range_type,
        date=event_date or date(2024, 6, 15),
        range_location_id=range_location.id,
        required_count=required_count,
        reserve_count=reserve_count,
        status=status,
    )
    session.add(event)
    session.flush()
    return event


def create_range_assignment(
    session: Session, *, range_event: RangeEvent, soldier: Soldier,
    is_reserve: bool = False, attendance_status: str = "pending",
) -> RangeAssignment:
    assignment = RangeAssignment(
        range_event_id=range_event.id, soldier_id=soldier.id,
        is_reserve=is_reserve, attendance_status=attendance_status,
    )
    session.add(assignment)
    session.flush()
    return assignment


def auth_headers(soldier: Soldier) -> dict[str, str]:
    token = issue_access_token(user_id=soldier.id, role=soldier.role)
    return {"Authorization": f"Bearer {token}"}
