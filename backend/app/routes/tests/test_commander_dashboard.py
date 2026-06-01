from __future__ import annotations

from unittest.mock import create_autospec

from sqlalchemy.orm import Session

from app.services import commander_dashboard as svc


def test_summary_cards_empty_subtree():
    """Empty subtree returns zeros."""
    session = create_autospec(Session)
    session.execute.return_value.scalar.return_value = 0
    session.execute.return_value.scalars.return_value.all.return_value = []
    session.execute.return_value.all.return_value = []
    result = svc.summary_cards(session, subtree_ids=[])
    assert result["approvals_pending"] == 0
    assert result["upcoming_duties_7d"] == 0
    assert result["unfilled_gaps"] == 0
    assert result["alerts_count"] == 0


def test_fairness_stats_empty():
    """No soldiers returns all-zero stats."""
    session = create_autospec(Session)
    result = svc.fairness_stats(session, subtree_ids=[])
    assert result["soldier_count"] == 0
    assert result["mean"] == 0.0


def test_potential_counts_no_soldiers():
    """Empty subtree returns labels with zero counts."""
    session = create_autospec(Session)
    result = svc.potential_counts(session, subtree_ids=[])
    assert len(result) == 5
    for item in result:
        assert item["count"] == 0
