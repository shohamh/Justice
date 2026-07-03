from __future__ import annotations

import uuid

from app.auth.authz import Action, can
from app.db.models import Soldier


def _soldier(rank=None, role="commander"):
    return Soldier(
        personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x",
        role=role, rank=rank,
    )


def test_commander_below_rasan_cannot_read_potential():
    s = _soldier(rank="סרן")
    node_id = uuid.uuid4()
    assert can(
        s, Action.POTENTIAL_READ, target_node=None, roots={node_id},
        is_commander=True, is_duty_manager=False,
    ) is False


def test_commander_rasan_and_above_can_read_potential():
    from app.db.models import HierarchyNode
    s = _soldier(rank="רסן")
    node = HierarchyNode(level="פלוגה", name="X", path_ids=[uuid.uuid4()])
    node.path_ids = [node.id] if node.id else [uuid.uuid4()]
    roots = {node.path_ids[0]}
    assert can(
        s, Action.POTENTIAL_READ, target_node=node, roots=roots,
        is_commander=True, is_duty_manager=False,
    ) is True


def test_duty_manager_can_read_potential_in_scope():
    from app.db.models import HierarchyNode
    s = _soldier(rank=None, role="duty_manager")
    node_id = uuid.uuid4()
    node = HierarchyNode(level="פלוגה", name="X", path_ids=[node_id])
    assert can(
        s, Action.POTENTIAL_READ, target_node=node, roots={node_id},
        is_commander=False, is_duty_manager=True,
    ) is True
