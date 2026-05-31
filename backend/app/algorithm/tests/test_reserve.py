from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.types import DutyBlock, SoldierInput
from app.algorithm.reserve import link_reserves, compute_reserve_dist


def _block(is_reserve: bool = False, start: date = date(2026, 6, 1), end: date = date(2026, 6, 1)) -> DutyBlock:
    return DutyBlock(
        id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
        start_date=start, end_date=end, score_per_day=Decimal("1"), is_reserve=is_reserve,
    )


def test_link_reserves_one_primary_one_reserve():
    shift_id = uuid4()
    primary_soldier = uuid4()
    reserve_soldier = uuid4()
    node = uuid4()
    primary_assignment_id = uuid4()
    reserve_assignment_id = uuid4()
    soldier_node = {primary_soldier: node, reserve_soldier: node}
    hierarchy_parent: dict = {node: None}

    links = link_reserves(
        primary_assignments=[(primary_assignment_id, primary_soldier, shift_id)],
        reserve_assignments=[(reserve_assignment_id, reserve_soldier, shift_id)],
        soldier_node=soldier_node,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children={node: []},
    )
    assert len(links) == 1
    assert links[0].reserve_assignment_id == reserve_assignment_id
    assert links[0].primary_assignment_id == primary_assignment_id
    assert links[0].hierarchy_distance == 0


def test_link_reserves_prefers_closest():
    shift_id = uuid4()
    root = uuid4(); child_a = uuid4(); child_b = uuid4()
    primary_soldier = uuid4(); reserve_close = uuid4(); reserve_far = uuid4()
    soldier_node = {primary_soldier: child_a, reserve_close: child_a, reserve_far: root}
    hierarchy_parent = {child_a: root, child_b: root, root: None}
    hierarchy_children = {root: [child_a, child_b], child_a: [], child_b: []}

    primary_id = uuid4(); reserve_close_id = uuid4(); reserve_far_id = uuid4()
    links = link_reserves(
        primary_assignments=[(primary_id, primary_soldier, shift_id)],
        reserve_assignments=[
            (reserve_close_id, reserve_close, shift_id),
            (reserve_far_id, reserve_far, shift_id),
        ],
        soldier_node=soldier_node,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children=hierarchy_children,
    )
    assert len(links) == 1
    assert links[0].primary_assignment_id == primary_id
    assert links[0].reserve_assignment_id == reserve_close_id
    assert links[0].hierarchy_distance == 0


def test_link_reserves_reserve_covers_multiple_primaries():
    shift_id = uuid4()
    node = uuid4()
    p1, p2, r = uuid4(), uuid4(), uuid4()
    soldier_node = {p1: node, p2: node, r: node}
    hierarchy_parent = {node: None}
    p1_id, p2_id, r_id = uuid4(), uuid4(), uuid4()
    links = link_reserves(
        primary_assignments=[(p1_id, p1, shift_id), (p2_id, p2, shift_id)],
        reserve_assignments=[(r_id, r, shift_id)],
        soldier_node=soldier_node,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children={node: []},
    )
    assert len(links) == 2
    assert all(lk.reserve_assignment_id == r_id for lk in links)
    assert {lk.primary_assignment_id for lk in links} == {p1_id, p2_id}


def test_compute_reserve_dist_same_node_is_zero():
    shift_id = uuid4()
    node = uuid4()
    primary_soldier = uuid4(); reserve_soldier = uuid4()
    soldier_node = {primary_soldier: node, reserve_soldier: node}
    primary_block = _block(is_reserve=False)
    reserve_block = _block(is_reserve=True)
    block_to_shift = {primary_block.id: shift_id, reserve_block.id: shift_id}
    soldiers = [
        SoldierInput(id=primary_soldier, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=reserve_soldier, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100),
    ]
    hierarchy_parent = {node: None}
    dist = compute_reserve_dist(
        soldiers=soldiers,
        duties=[primary_block, reserve_block],
        block_to_shift=block_to_shift,
        hierarchy_parent=hierarchy_parent,
        soldier_node=soldier_node,
    )
    # reserve block is index 1; reserve_soldier is index 1
    assert dist.get((1, 1), 99) == 0
