from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.reserve import select_reserves
from app.algorithm.types import Assignment, DutyBlock, SoldierInput


def test_select_reserves_basic_hierarchy_walk() -> None:
    team_a = uuid4()
    team_b = uuid4()
    group = uuid4()
    soldier_primary = uuid4()
    soldier_backup = uuid4()

    soldiers = [
        SoldierInput(id=soldier_primary, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_a),
        SoldierInput(id=soldier_backup, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_b),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=soldier_primary)]

    hierarchy_parent = {team_a: group, team_b: group, group: None}
    hierarchy_children = {group: [team_a, team_b], team_a: [], team_b: []}
    soldier_node = {soldier_primary: team_a, soldier_backup: team_b}
    node_soldiers = {team_a: [soldier_primary], team_b: [soldier_backup]}

    result = select_reserves(
        soldiers=soldiers,
        duties=duties,
        assignments=assignments,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children=hierarchy_children,
        soldier_node=soldier_node,
        node_soldiers=node_soldiers,
    )
    assert len(result) == 1
    assert result[0].duty_id == duties[0].id
    assert result[0].primary_soldier_id == soldier_primary
    assert result[0].reserve_soldier_id == soldier_backup


def test_no_reserve_available() -> None:
    solo = uuid4()
    team = uuid4()
    soldiers = [SoldierInput(id=solo, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100,
                             hierarchy_node_id=team)]
    duties = [DutyBlock(id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=solo)]
    result = select_reserves(
        soldiers=soldiers, duties=duties, assignments=assignments,
        hierarchy_parent={team: None}, hierarchy_children={team: []},
        soldier_node={solo: team}, node_soldiers={team: [solo]},
    )
    assert len(result) == 0


def test_reserve_skips_exempted_soldier() -> None:
    primary = uuid4()
    backup = uuid4()
    team_a = uuid4()
    team_b = uuid4()
    group = uuid4()
    duty_type = uuid4()

    soldiers = [
        SoldierInput(id=primary, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_a),
        SoldierInput(id=backup, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_b,
                     exempted_duty_type_ids={duty_type}),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=primary)]

    result = select_reserves(
        soldiers=soldiers, duties=duties, assignments=assignments,
        hierarchy_parent={team_a: group, team_b: group, group: None},
        hierarchy_children={group: [team_a, team_b], team_a: [], team_b: []},
        soldier_node={primary: team_a, backup: team_b},
        node_soldiers={team_a: [primary], team_b: [backup]},
    )
    assert len(result) == 0
