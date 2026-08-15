from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.algorithm.saturation import _eligible, analyze_saturation
from app.algorithm.types import Assignment, DutyBlock, ExistingAssignment, SoldierInput


def test_analyze_saturation_reports_zero_free_and_competing_duty_types():
    competing_type_a = uuid4()
    competing_type_b = uuid4()
    saturated_type = uuid4()
    loc = uuid4()
    base = date(2026, 7, 6)
    end = base + timedelta(days=9)

    soldier_a = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
    soldier_b = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
    full_pool = [soldier_a, soldier_b]

    unassigned_duty = DutyBlock(id=uuid4(), duty_type_id=saturated_type, duty_location_id=loc,
                                start_date=base, end_date=end, score_per_day=Decimal("1.00"))

    # Both soldiers are already committed elsewhere during the unassigned duty's window.
    existing = [
        ExistingAssignment(soldier_id=soldier_a.id, duty_type_id=competing_type_a,
                           start_date=base, end_date=end, is_reserve=True),
        ExistingAssignment(soldier_id=soldier_b.id, duty_type_id=competing_type_b,
                           start_date=base, end_date=end, is_reserve=True),
    ]

    duty_by_id = {unassigned_duty.id: unassigned_duty}
    clusters = analyze_saturation(
        unassigned=[unassigned_duty], full_pool=full_pool, all_assignments=[],
        existing=existing, duty_by_id=duty_by_id,
    )

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.date_from == base
    assert cluster.date_to == end
    assert cluster.shift_ids == [unassigned_duty.id]
    assert cluster.eligible_pool_size == 2
    assert cluster.free_count == 0
    competing = dict(cluster.competing_duty_types)
    assert competing[competing_type_a] == 1
    assert competing[competing_type_b] == 1


def test_analyze_saturation_groups_overlapping_duties_into_one_cluster():
    dt = uuid4()
    loc = uuid4()
    base = date(2026, 7, 6)
    d1 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=base, end_date=base + timedelta(days=9), score_per_day=Decimal("1.00"))
    d2 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=base, end_date=base + timedelta(days=8), score_per_day=Decimal("1.00"))
    # Disjoint date range -> separate cluster.
    d3 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=base + timedelta(days=30), end_date=base + timedelta(days=39),
                  score_per_day=Decimal("1.00"))
    soldier = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)

    clusters = analyze_saturation(
        unassigned=[d1, d2, d3], full_pool=[soldier], all_assignments=[], existing=[],
        duty_by_id={d.id: d for d in (d1, d2, d3)},
    )

    by_size = sorted(len(c.shift_ids) for c in clusters)
    assert by_size == [1, 2]


def test_analyze_saturation_reports_free_soldiers_when_not_saturated():
    dt = uuid4()
    loc = uuid4()
    base = date(2026, 7, 6)
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                     start_date=base, end_date=base + timedelta(days=1), score_per_day=Decimal("1.00"))
    soldier = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)

    clusters = analyze_saturation(
        unassigned=[duty], full_pool=[soldier], all_assignments=[], existing=[],
        duty_by_id={duty.id: duty},
    )
    assert clusters[0].free_count == 1
    assert clusters[0].competing_duty_types == []


def test_analyze_saturation_returns_empty_for_no_unassigned_duties():
    assert analyze_saturation(unassigned=[], full_pool=[], all_assignments=[], existing=[], duty_by_id={}) == []


def test_eligible_subtree_match():
    """A soldier in a sub-team under a scoped node is eligible (subtree match,
    not exact match) -- mirrors solver._eligible_pairs' filter."""
    root = uuid4()
    child = uuid4()
    dt = uuid4()
    loc = uuid4()

    soldier = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                            active_days=100, hierarchy_node_id=child, path_ids=[root, child])
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root])

    assert _eligible(soldier, duty) is True


def test_eligible_excludes_range_ineligible_soldier_from_saturation_pool():
    duty = DutyBlock(
        id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        score_per_day=Decimal("1"), required_range_type="laser",
    )
    soldier = SoldierInput(
        id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100,
        weapon_ineligible_duty_block_ids={duty.id},
    )

    assert _eligible(soldier, duty) is False
