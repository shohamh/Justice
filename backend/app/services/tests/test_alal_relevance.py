from __future__ import annotations

from app.db.models import DutyType, RangeType
from app.services.alal_relevance import invalidate_alal_relevance_cache, is_alal_relevant
from tests.helpers import create_node, create_soldier


def test_soldier_in_scope_of_alal_duty_type_is_relevant(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-1")
    soldier = create_soldier(app_session, personal_number="alal-rel-001", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is True


def test_soldier_with_only_non_alal_duty_types_is_not_relevant(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-2")
    soldier = create_soldier(app_session, personal_number="alal-rel-002", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-2", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    ))
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is False


def test_soldier_with_no_hierarchy_node_is_not_relevant(app_session) -> None:
    soldier = create_soldier(app_session, personal_number="alal-rel-003", hierarchy_node_id=None)
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is False


def test_cache_reflects_new_duty_type_only_after_invalidation(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-4")
    soldier = create_soldier(app_session, personal_number="alal-rel-004", hierarchy_node_id=node.id)
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is False

    app_session.add(DutyType(
        name="alal-rel-duty-4", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False  # stale cache, not yet invalidated
    invalidate_alal_relevance_cache()
    assert is_alal_relevant(app_session, soldier) is True
