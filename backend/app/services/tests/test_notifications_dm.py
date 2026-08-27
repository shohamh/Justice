# backend/app/services/tests/test_notifications_dm.py
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.db.models import (
    DutyManagerScope,
    HierarchyLevelType,
    HierarchyNode,
    Notification,
    NotificationType,
    Soldier,
)
from app.services.notifications import notify_duty_managers_of_request


@pytest.fixture(autouse=True)
def _clear_seeded_level_types(app_session):
    """This module defines its own Hebrew-keyed levels/ranks — see
    app/services/tests/test_authority.py for why the shared English-keyed
    defaults must be cleared first."""
    app_session.execute(delete(HierarchyLevelType))
    app_session.flush()


def _level(session, key, rank):
    lt = HierarchyLevelType(key=key, label=key, rank=rank)
    session.add(lt)
    session.flush()
    return lt


def _soldier(session, **kw):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", **kw)
    session.add(s)
    session.flush()
    return s


def test_notifies_dm_whose_scope_meets_rank_but_not_below_rank_dm(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "department", 2)
    _level(app_session, "פלוגה", 3)

    center_node = HierarchyNode(level="department", name="Center", path_ids=[])
    app_session.add(center_node)
    app_session.flush()
    center_node.path_ids = [center_node.id]

    co_node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(co_node)
    app_session.flush()
    co_node.path_ids = [center_node.id, co_node.id]
    app_session.flush()

    soldier = _soldier(app_session, hierarchy_node_id=co_node.id)
    qualified_dm = _soldier(app_session)
    unqualified_dm = _soldier(app_session)
    app_session.add(DutyManagerScope(duty_manager_id=qualified_dm.id, hierarchy_node_id=center_node.id))
    app_session.add(DutyManagerScope(duty_manager_id=unqualified_dm.id, hierarchy_node_id=co_node.id))
    app_session.flush()

    notify_duty_managers_of_request(
        app_session,
        soldier_id=soldier.id,
        type=NotificationType.exemption_request_pending,
        title="בקשת פטור חדשה",
    )

    notified_ids = set(
        app_session.execute(select(Notification.soldier_id)).scalars().all()
    )
    assert qualified_dm.id in notified_ids
    assert unqualified_dm.id not in notified_ids
