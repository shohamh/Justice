from __future__ import annotations

from app.services.hr.hierarchy_sync import _topological_order
from app.services.hr.schemas import HrGroup


def _group(id: str, name: str, parent_id: str | None = None, kind: str = "unit") -> HrGroup:
    return HrGroup(id=id, name=name, kind=kind, parent_id=parent_id)


def test_topological_order_root_before_children_even_when_input_is_reversed():
    grandchild = _group("gc", "Grandchild", parent_id="c")
    child = _group("c", "Child", parent_id="r")
    root = _group("r", "Root", parent_id=None)

    ordered = _topological_order([grandchild, child, root])

    ids = [g.id for g in ordered]
    assert ids.index("r") < ids.index("c") < ids.index("gc")
    assert len(ordered) == 3


def test_topological_order_multiple_roots_and_interleaved_children():
    r1 = _group("r1", "Root 1")
    r2 = _group("r2", "Root 2")
    c1 = _group("c1", "Child 1", parent_id="r1")
    c2 = _group("c2", "Child 2", parent_id="r2")

    ordered = _topological_order([c1, r1, c2, r2])

    ids = [g.id for g in ordered]
    assert ids.index("r1") < ids.index("c1")
    assert ids.index("r2") < ids.index("c2")
    assert len(ordered) == 4


def test_topological_order_dangling_parent_reference_is_still_included():
    orphan = _group("o", "Orphan", parent_id="missing-parent-id")

    ordered = _topological_order([orphan])

    assert [g.id for g in ordered] == ["o"]


def test_topological_order_cycle_does_not_infinite_loop_and_includes_both():
    a = _group("a", "A", parent_id="b")
    b = _group("b", "B", parent_id="a")

    ordered = _topological_order([a, b])

    assert {g.id for g in ordered} == {"a", "b"}
    assert len(ordered) == 2
