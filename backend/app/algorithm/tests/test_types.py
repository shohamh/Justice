from __future__ import annotations

import uuid

from app.algorithm.types import node_in_scope


def test_node_in_scope_none_scope_means_unrestricted() -> None:
    assert node_in_scope(None, [uuid.uuid4()]) is True
    assert node_in_scope(None, []) is True


def test_node_in_scope_exact_node_match() -> None:
    node = uuid.uuid4()
    assert node_in_scope([node], [node]) is True


def test_node_in_scope_descendant_matches_ancestor_scope() -> None:
    root = uuid.uuid4()
    child = uuid.uuid4()
    # soldier's path_ids includes every ancestor up to itself (materialized path)
    assert node_in_scope([root], [root, child]) is True


def test_node_in_scope_unrelated_node_does_not_match() -> None:
    scoped = uuid.uuid4()
    other_root = uuid.uuid4()
    other_child = uuid.uuid4()
    assert node_in_scope([scoped], [other_root, other_child]) is False


def test_node_in_scope_unassigned_soldier_excluded_when_scope_set() -> None:
    assert node_in_scope([uuid.uuid4()], []) is False
