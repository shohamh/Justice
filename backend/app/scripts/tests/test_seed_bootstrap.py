"""Regression test: reseeding must not orphan the bootstrapped root/holding
nodes. bootstrap.py's node creation is idempotent based on SystemSetting rows,
so calling it before a --force wipe (which deletes all HierarchyNode rows)
used to leave those settings dangling forever after the first reseed.

Imports of app.db.session / app.scripts.seed are deferred into the test body
(not module top-level) because importing app.db.session eagerly creates its
module-global engine from the ambient DATABASE_URL — which must happen after
the session-scoped _apply_schema fixture has pointed it at the test container.
"""
from __future__ import annotations


def test_reseeding_twice_keeps_root_and_holding_nodes_alive(db_admin_url: str):
    import uuid

    from app.db.models import HierarchyNode, SystemSetting
    from app.db.session import SessionLocal
    from app.scripts import seed as seed_module

    seed_module.seed(force=True)

    with SessionLocal() as s:
        root_setting = s.get(SystemSetting, "system.root_node_id")
        assert root_setting is not None
        root = s.get(HierarchyNode, uuid.UUID(root_setting.value))
        assert root is not None
        assert root.name == "כלל המסגרת"
        assert root.parent_id is None

        holding_setting = s.get(SystemSetting, "system.holding_node_id")
        assert holding_setting is not None
        holding = s.get(HierarchyNode, uuid.UUID(holding_setting.value))
        assert holding is not None
        assert holding.parent_id == root.id, "holding node must nest under the root, not be a second root"

        psips = s.query(HierarchyNode).filter(HierarchyNode.name == "פסיפס").one()
        assert psips.parent_id == root.id

    # A second --force reseed is where the bug used to bite: bootstrap saw the
    # SystemSetting rows already present and skipped recreating the nodes the
    # first reseed's wipe had just deleted.
    seed_module.seed(force=True)

    with SessionLocal() as s:
        root_setting = s.get(SystemSetting, "system.root_node_id")
        assert root_setting is not None
        root = s.get(HierarchyNode, uuid.UUID(root_setting.value))
        assert root is not None, "root node must survive a second reseed"
        assert root.name == "כלל המסגרת"

        holding_setting = s.get(SystemSetting, "system.holding_node_id")
        assert holding_setting is not None
        holding = s.get(HierarchyNode, uuid.UUID(holding_setting.value))
        assert holding is not None, "holding node must survive a second reseed"
        assert holding.parent_id == root.id, "holding node must nest under the root, not be a second root"

        psips = s.query(HierarchyNode).filter(HierarchyNode.name == "פסיפס").one()
        assert psips.parent_id == root.id


def test_seed_creates_stable_range_scenarios_without_duplicates(db_admin_url: str):
    from datetime import date

    from app.db.models import RangeAssignment, RangeAttendanceStatus, RangeEvent, SystemSetting
    from app.db.session import SessionLocal
    from app.scripts import seed as seed_module

    seed_module.seed(force=True)
    seed_module.seed()

    with SessionLocal() as s:
        assert s.get(SystemSetting, "mitvachim.enabled").value is True
        events = s.query(RangeEvent).all()
        assert len(events) == 3
        past_no_show = [e for e in events if e.date < date.today() and any(
            a.attendance_status == RangeAttendanceStatus.no_show
            for a in s.query(RangeAssignment).filter_by(range_event_id=e.id).all()
        )]
        upcoming_staffed = [e for e in events if e.date > date.today() and s.query(RangeAssignment).filter_by(range_event_id=e.id).count() > 0]
        upcoming_empty = [e for e in events if e.date > date.today() and s.query(RangeAssignment).filter_by(range_event_id=e.id).count() == 0]
        assert len(past_no_show) == 1
        assert len(upcoming_staffed) == 1
        assert len(upcoming_empty) == 1
