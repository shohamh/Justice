from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth.jwt_tokens import issue_access_token
from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier


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
    node = HierarchyNode(level=level, name=name, parent_id=parent.id if parent else None, commander_id=commander_id)
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = ([*parent.path_ids, node.id] if parent else [node.id])
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
) -> Soldier:
    s = Soldier(
        personal_number=personal_number,
        full_name=f"Test {personal_number}",
        password_hash=hash_password(password),
        role=role,
        hierarchy_node_id=hierarchy_node_id,
        must_change_password=must_change_password,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def auth_headers(soldier: Soldier) -> dict[str, str]:
    token = issue_access_token(user_id=soldier.id, role=soldier.role)
    return {"Authorization": f"Bearer {token}"}
