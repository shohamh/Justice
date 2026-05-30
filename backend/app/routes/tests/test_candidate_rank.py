from __future__ import annotations

from app.routes.algorithm import _compute_candidate_rank


def test_assigned_soldier_is_rank_1_when_lowest_score() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": 0.5},
        {"soldier_id": "b", "blocked": False, "pre_norm_score": 1.0},
        {"soldier_id": "c", "blocked": True,  "pre_norm_score": 0.1},  # excluded
    ]
    rank, pool = _compute_candidate_rank(candidates, "a")
    assert rank == 1
    assert pool == 2


def test_second_lowest_score_is_rank_2() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": 2.0},
        {"soldier_id": "b", "blocked": False, "pre_norm_score": 1.0},
        {"soldier_id": "c", "blocked": False, "pre_norm_score": 3.0},
    ]
    rank, pool = _compute_candidate_rank(candidates, "a")
    assert rank == 2
    assert pool == 3


def test_soldier_not_in_unblocked_returns_none_rank() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": 1.0},
    ]
    rank, pool = _compute_candidate_rank(candidates, "x")
    assert rank is None
    assert pool == 1


def test_null_score_sorts_last() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": None},
        {"soldier_id": "b", "blocked": False, "pre_norm_score": 1.0},
    ]
    rank, pool = _compute_candidate_rank(candidates, "b")
    assert rank == 1
    assert pool == 2


def test_empty_candidates_returns_none() -> None:
    rank, pool = _compute_candidate_rank([], "a")
    assert rank is None
    assert pool == 0
