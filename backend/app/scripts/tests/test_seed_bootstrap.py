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


def test_seed_duty_types_require_at_least_a_laser_range(db_admin_url: str):
    from app.db.models import DutyType, RangeType
    from app.db.session import SessionLocal
    from app.scripts import seed as seed_module

    seed_module.seed(force=True)

    with SessionLocal() as s:
        required_range_types = {
            duty_type.name: duty_type.required_range_type
            for duty_type in s.query(DutyType).filter(
                DutyType.name.in_(
                    ["שמירות", "קצין תורן", "קצין מלווה אבט\"ש", "מפקד תורן"]
                )
            ).all()
        }

    assert required_range_types == {
        "שמירות": RangeType.laser,
        "קצין תורן": RangeType.laser,
        "קצין מלווה אבט\"ש": RangeType.laser,
        "מפקד תורן": RangeType.laser,
    }


def test_seed_creates_rank_advancement_defaults(db_admin_url: str):
    from app.db.models import RankAdvancementInterval
    from app.db.session import SessionLocal
    from app.scripts import seed as seed_module

    seed_module.seed(force=True)

    with SessionLocal() as s:
        rows = s.query(RankAdvancementInterval).all()

    actual = {
        (row.track, row.rank): (row.months_to_next, row.advance_on_career_entry)
        for row in rows
    }
    assert actual == {
        ("enlisted", "טוראי"): (10, False),
        ("enlisted", "רבט"): (11, False),
        ("enlisted", "סמל"): (11, True),
        ("enlisted", "סמר"): (24, False),
        ("enlisted", "רסל"): (None, False),
        ("enlisted", "רסר"): (None, False),
        ("enlisted", "רסמ"): (None, False),
        ("enlisted", "רסב"): (None, False),
        ("enlisted", "רנג"): (None, False),
        ("officer", "סגמ"): (12, True),
        ("officer", "סגן"): (36, False),
        ("officer", "סרן"): (48, False),
        ("officer", "רסן"): (None, False),
        ("officer", "סאל"): (None, False),
        ("officer", "אלמ"): (None, False),
        ("officer", "תאל"): (None, False),
        ("officer", "אלוף"): (None, False),
        ("officer", "רב אלוף"): (None, False),
        ("officer_academic", "קמא"): (32, True),
        ("officer_academic", "קאב"): (None, False),
        ("officer_academic", "סגן"): (12, True),
        ("officer_academic", "סרן"): (36, False),
        ("officer_academic", "רסן"): (None, False),
        ("officer_academic", "סאל"): (None, False),
        ("officer_academic", "אלמ"): (None, False),
        ("officer_academic", "תאל"): (None, False),
        ("officer_academic", "אלוף"): (None, False),
        ("officer_academic", "רב אלוף"): (None, False),
        ("officer_academic", "קאם"): (None, False),
    }


def test_seed_preserves_custom_rank_advancement_intervals(db_admin_url: str):
    from app.db.models import RankAdvancementInterval
    from app.db.session import SessionLocal
    from app.scripts import seed as seed_module

    seed_module.seed(force=True)
    with SessionLocal() as s:
        row = s.query(RankAdvancementInterval).filter_by(track="enlisted", rank="טוראי").one()
        row.months_to_next = 99
        row.advance_on_career_entry = True
        s.commit()

    seed_module.seed()

    with SessionLocal() as s:
        row = s.query(RankAdvancementInterval).filter_by(track="enlisted", rank="טוראי").one()
        assert (row.months_to_next, row.advance_on_career_entry) == (99, True)
