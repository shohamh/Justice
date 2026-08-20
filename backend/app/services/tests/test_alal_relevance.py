from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db.models import DutyType, ExemptionDutyTypeMap, ExemptionType, RangeType, SoldierExemption
from app.services.alal_relevance import active_alal_duty_types, is_alal_relevant
from tests.helpers import create_node, create_soldier


def _grant_exemption(session, soldier_id, *, is_global=False, forbids_weapons=False,
                      start_date=None, end_date=None, duty_type_ids=None):
    et = ExemptionType(
        name=f"alal-exempt-{soldier_id}-{is_global}-{forbids_weapons}-{duty_type_ids}",
        is_global=is_global, forbids_weapons=forbids_weapons,
    )
    session.add(et)
    session.flush()
    for duty_type_id in duty_type_ids or []:
        session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=duty_type_id))
    se = SoldierExemption(
        soldier_id=soldier_id, exemption_type_id=et.id,
        start_date=start_date or date(2020, 1, 1), end_date=end_date,
    )
    session.add(se)
    session.flush()
    return se


def test_soldier_in_scope_of_alal_duty_type_is_relevant(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-1")
    soldier = create_soldier(app_session, personal_number="alal-rel-001", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is True


def test_soldier_with_only_non_alal_duty_types_is_not_relevant(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-2")
    soldier = create_soldier(app_session, personal_number="alal-rel-002", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-2", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False


def test_soldier_with_no_hierarchy_node_is_not_relevant(app_session) -> None:
    soldier = create_soldier(app_session, personal_number="alal-rel-003", hierarchy_node_id=None)
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False


def test_duty_type_change_is_reflected_on_next_call_with_no_invalidation_step(app_session) -> None:
    """is_alal_relevant() queries directly (no cache), so a duty-type write is
    visible on the very next call — no explicit invalidation is needed. This
    replaces the old cache-staleness test, since caching this value per-process
    was unsafe under the multi-worker prod deploy (each worker has its own
    process memory, so one worker's invalidation never reached the others)."""
    node = create_node(app_session, level="team", name="alal-rel-team-4")
    soldier = create_soldier(app_session, personal_number="alal-rel-004", hierarchy_node_id=node.id)
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False

    app_session.add(DutyType(
        name="alal-rel-duty-4", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is True


def test_permanent_global_exemption_suppresses_relevance(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-5")
    soldier = create_soldier(app_session, personal_number="alal-rel-005", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-5", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    _grant_exemption(app_session, soldier.id, is_global=True, end_date=None)
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False


def test_forbids_weapons_exemption_ending_far_in_future_suppresses(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-6")
    soldier = create_soldier(app_session, personal_number="alal-rel-006", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-6", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        end_date=date.today() + timedelta(days=100),
    )
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False


def test_exemption_ending_within_90_days_does_not_suppress(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-7")
    soldier = create_soldier(app_session, personal_number="alal-rel-007", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-7", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        end_date=date.today() + timedelta(days=30),
    )
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is True


def test_duty_type_specific_exemption_covering_all_alal_duty_types_suppresses(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-8")
    soldier = create_soldier(app_session, personal_number="alal-rel-008", hierarchy_node_id=node.id)
    duty_a = DutyType(
        name="alal-rel-duty-8a", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    )
    duty_b = DutyType(
        name="alal-rel-duty-8b", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    )
    app_session.add_all([duty_a, duty_b])
    app_session.flush()
    _grant_exemption(
        app_session, soldier.id, end_date=None, duty_type_ids=[duty_a.id, duty_b.id],
    )
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False


def test_duty_type_specific_exemption_covering_only_some_alal_duty_types_does_not_suppress(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-9")
    soldier = create_soldier(app_session, personal_number="alal-rel-009", hierarchy_node_id=node.id)
    duty_a = DutyType(
        name="alal-rel-duty-9a", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    )
    duty_b = DutyType(
        name="alal-rel-duty-9b", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    )
    app_session.add_all([duty_a, duty_b])
    app_session.flush()
    _grant_exemption(
        app_session, soldier.id, end_date=None, duty_type_ids=[duty_a.id],
    )
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is True


def test_revoked_exemption_does_not_suppress(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-10")
    soldier = create_soldier(app_session, personal_number="alal-rel-010", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-10", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    exemption = _grant_exemption(app_session, soldier.id, is_global=True, end_date=None)
    exemption.revoked_at = datetime.now()
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is True


def test_active_alal_duty_types_returns_all_active_alal_types_unfiltered_by_node(app_session) -> None:
    node_a = create_node(app_session, level="team", name="alal-rel-team-11a")
    node_b = create_node(app_session, level="team", name="alal-rel-team-11b")
    alal_a = DutyType(
        name="alal-rel-duty-11a", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node_a.id],
    )
    alal_b = DutyType(
        name="alal-rel-duty-11b", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node_b.id],
    )
    inactive_alal = DutyType(
        name="alal-rel-duty-11c", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node_a.id], active=False,
    )
    non_alal = DutyType(
        name="alal-rel-duty-11d", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.laser, eligible_node_ids=[node_a.id],
    )
    app_session.add_all([alal_a, alal_b, inactive_alal, non_alal])
    app_session.commit()

    result_ids = {dt.id for dt in active_alal_duty_types(app_session)}

    assert result_ids == {alal_a.id, alal_b.id}


def test_is_alal_relevant_uses_the_provided_active_duty_types_instead_of_querying(app_session) -> None:
    """Passing active_alal_duty_types must actually be used -- not just accepted
    and ignored -- so a worker scanning many soldiers can fetch the active list
    once instead of re-querying per soldier."""
    node = create_node(app_session, level="team", name="alal-rel-team-12")
    soldier = create_soldier(app_session, personal_number="alal-rel-012", hierarchy_node_id=node.id)
    app_session.commit()  # deliberately no committed alal DutyType -- a fresh query would find none

    uncommitted_alal_duty_type = DutyType(
        name="alal-rel-duty-12", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    )

    assert is_alal_relevant(
        app_session, soldier, active_alal_duty_types=[uncommitted_alal_duty_type],
    ) is True


def test_is_alal_relevant_with_provided_types_still_respects_node_scope(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-13")
    other_node = create_node(app_session, level="team", name="alal-rel-team-13b")
    soldier = create_soldier(app_session, personal_number="alal-rel-013", hierarchy_node_id=node.id)
    app_session.commit()

    out_of_scope_alal_duty_type = DutyType(
        name="alal-rel-duty-13", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[other_node.id],
    )

    assert is_alal_relevant(
        app_session, soldier, active_alal_duty_types=[out_of_scope_alal_duty_type],
    ) is False
