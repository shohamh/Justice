from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    RangeAssignment,
    RangeEvent,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.range_eligibility_projection import (
    count_ineligible_soldiers_for_duties,
    project_duty_eligibility,
)
from app.services.settings_loader import set_setting
from tests.helpers import create_duty_location, create_node, create_range_location, create_soldier

# Keep planned-range fixtures safely inside weapon_eligibility's real today-based
# future window while still testing coverage at the scheduled duty date.
AS_OF = date.today() + timedelta(days=6)


def _enable_enforcement(session: Session) -> None:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)


def _duty(
    session: Session, *, soldier_id, required_range_type: RangeType, start_date: date
) -> DutyAssignment:
    duty_type = DutyType(
        name=f"projection-duty-{required_range_type.value}-{soldier_id}-{start_date}",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        required_range_type=required_range_type,
    )
    session.add(duty_type)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type.id,
        duty_location_id=create_duty_location(session).id,
        start_date=start_date,
        end_date=start_date,
    )
    session.add(assignment)
    session.flush()
    return assignment


def _planned_range(
    session: Session,
    *,
    soldier_id,
    node_id,
    range_type: RangeType,
    event_date: date,
    is_reserve: bool = False,
    is_draft: bool = False,
    pending_excusal: bool = False,
) -> RangeAssignment:
    event = RangeEvent(
        hierarchy_node_id=node_id,
        range_type=range_type,
        date=event_date,
        range_location_id=create_range_location(session).id,
        required_count=1,
    )
    session.add(event)
    session.flush()
    assignment = RangeAssignment(
        range_event_id=event.id,
        soldier_id=soldier_id,
        is_reserve=is_reserve,
        is_draft=is_draft,
    )
    session.add(assignment)
    session.flush()
    if pending_excusal:
        session.add(
            RangeExcusalRequest(
                range_assignment_id=assignment.id,
                requested_by=soldier_id,
                reason="pending",
                status=RangeExcusalStatus.pending,
            )
        )
    return assignment


def test_projects_exact_and_higher_tier_qualifications_at_each_duty_date(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="projection-tier")
    exact = create_soldier(
        app_session, personal_number="projection-exact", hierarchy_node_id=node.id
    )
    higher = create_soldier(
        app_session, personal_number="projection-higher", hierarchy_node_id=node.id
    )
    exact_duty = _duty(
        app_session, soldier_id=exact.id, required_range_type=RangeType.laser, start_date=AS_OF
    )
    higher_duty = _duty(
        app_session, soldier_id=higher.id, required_range_type=RangeType.laser, start_date=AS_OF
    )
    _enable_enforcement(app_session)
    app_session.add_all(
        [
            SoldierRangeQualification(
                soldier_id=exact.id, range_type=RangeType.laser, valid_until=AS_OF
            ),
            SoldierRangeQualification(
                soldier_id=higher.id,
                range_type=RangeType.alal,
                valid_until=AS_OF + timedelta(days=1),
            ),
        ]
    )
    app_session.commit()

    facts = project_duty_eligibility(
        app_session,
        soldier_ids=[exact.id, higher.id],
        duty_ids=[exact_duty.id, higher_duty.id],
        as_of=AS_OF,
    )

    assert facts[exact.id, exact_duty.id].eligible is True
    assert facts[exact.id, exact_duty.id].qualification_source == "current_qualification"
    assert facts[higher.id, higher_duty.id].eligible is True
    assert facts[higher.id, higher_duty.id].projected_valid_until == AS_OF + timedelta(days=1)


def test_uses_the_duty_date_so_an_expired_qualification_is_ineligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="projection-expired")
    duty = _duty(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, start_date=AS_OF
    )
    _enable_enforcement(app_session)
    app_session.add(
        SoldierRangeQualification(
            soldier_id=soldier.id, range_type=RangeType.laser, valid_until=AS_OF - timedelta(days=1)
        )
    )
    app_session.commit()

    fact = project_duty_eligibility(
        app_session,
        soldier_ids=[soldier.id],
        duty_ids=[duty.id],
        as_of=date.today(),
    )[soldier.id, duty.id]

    assert fact.eligible is False
    assert fact.reason == "weapon_qualification"
    assert fact.qualification_source is None


def test_projects_a_confirmed_main_range_assignment_that_covers_the_duty(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="projection-planned")
    soldier = create_soldier(
        app_session, personal_number="projection-planned", hierarchy_node_id=node.id
    )
    duty = _duty(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, start_date=AS_OF
    )
    _enable_enforcement(app_session)
    _planned_range(
        app_session,
        soldier_id=soldier.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF - timedelta(days=1),
    )
    app_session.commit()

    fact = project_duty_eligibility(
        app_session,
        soldier_ids=[soldier.id],
        duty_ids=[duty.id],
        as_of=date.today(),
    )[soldier.id, duty.id]

    assert fact.eligible is True
    assert fact.qualification_source == "planned_range"
    assert fact.covered_by_range_date == AS_OF - timedelta(days=1)
    assert fact.projected_valid_until == AS_OF + timedelta(days=179)


def test_as_of_sets_the_planned_range_window_without_changing_the_duty_date(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="projection-as-of")
    soldier = create_soldier(
        app_session, personal_number="projection-as-of", hierarchy_node_id=node.id
    )
    range_date = date.today() + timedelta(days=1)
    duty = _duty(
        app_session,
        soldier_id=soldier.id,
        required_range_type=RangeType.laser,
        start_date=range_date + timedelta(days=1),
    )
    _enable_enforcement(app_session)
    _planned_range(
        app_session,
        soldier_id=soldier.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=range_date,
    )
    app_session.commit()

    fact = project_duty_eligibility(
        app_session,
        soldier_ids=[soldier.id],
        duty_ids=[duty.id],
        as_of=range_date + timedelta(days=1),
    )[soldier.id, duty.id]

    assert fact.eligible is False
    assert fact.reason == "weapon_qualification"


def test_historical_as_of_never_makes_a_past_range_future_coverage(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="projection-historical-as-of")
    soldier = create_soldier(
        app_session, personal_number="projection-historical-as-of", hierarchy_node_id=node.id
    )
    range_date = date.today() - timedelta(days=1)
    duty = _duty(
        app_session,
        soldier_id=soldier.id,
        required_range_type=RangeType.laser,
        start_date=date.today(),
    )
    _enable_enforcement(app_session)
    _planned_range(
        app_session,
        soldier_id=soldier.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=range_date,
    )
    app_session.commit()

    fact = project_duty_eligibility(
        app_session,
        soldier_ids=[soldier.id],
        duty_ids=[duty.id],
        as_of=range_date,
    )[soldier.id, duty.id]

    assert fact.eligible is False
    assert fact.reason == "weapon_qualification"


def test_reserve_draft_and_pending_excusal_range_assignments_do_not_project_eligibility(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="projection-exclusions")
    soldiers = [
        create_soldier(
            app_session, personal_number=f"projection-exclusion-{index}", hierarchy_node_id=node.id
        )
        for index in range(3)
    ]
    duties = [
        _duty(
            app_session,
            soldier_id=soldier.id,
            required_range_type=RangeType.laser,
            start_date=AS_OF,
        )
        for soldier in soldiers
    ]
    _enable_enforcement(app_session)
    _planned_range(
        app_session,
        soldier_id=soldiers[0].id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
        is_reserve=True,
    )
    _planned_range(
        app_session,
        soldier_id=soldiers[1].id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
        is_draft=True,
    )
    _planned_range(
        app_session,
        soldier_id=soldiers[2].id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
        pending_excusal=True,
    )
    app_session.commit()

    facts = project_duty_eligibility(
        app_session,
        soldier_ids=[soldier.id for soldier in soldiers],
        duty_ids=[duty.id for duty in duties],
        as_of=AS_OF,
    )

    assert all(
        facts[soldier.id, duty.id].eligible is False
        for soldier, duty in zip(soldiers, duties, strict=True)
    )


def test_pending_excusal_setting_can_keep_a_planned_main_assignment_eligible(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="projection-pending-setting")
    soldier = create_soldier(
        app_session,
        personal_number="projection-pending-setting",
        hierarchy_node_id=node.id,
    )
    duty = _duty(
        app_session,
        soldier_id=soldier.id,
        required_range_type=RangeType.laser,
        start_date=AS_OF,
    )
    _enable_enforcement(app_session)
    set_setting(
        app_session,
        "weapon_qualification.pending_excusal_disqualifies",
        False,
        actor_id=None,
    )
    _planned_range(
        app_session,
        soldier_id=soldier.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
        pending_excusal=True,
    )
    app_session.commit()

    fact = project_duty_eligibility(
        app_session, soldier_ids=[soldier.id], duty_ids=[duty.id], as_of=AS_OF
    )[soldier.id, duty.id]

    assert fact.eligible is True
    assert fact.qualification_source == "planned_range"


def test_disabled_enforcement_returns_an_explained_eligible_fact(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="projection-disabled")
    duty = _duty(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal, start_date=AS_OF
    )
    app_session.commit()

    fact = project_duty_eligibility(
        app_session, soldier_ids=[soldier.id], duty_ids=[duty.id], as_of=AS_OF
    )[soldier.id, duty.id]

    assert fact.eligible is True
    assert fact.reason is None
    assert fact.qualification_source == "enforcement_disabled"


def test_projects_each_required_tier_and_counts_each_ineligible_soldier_once(
    app_session: Session,
) -> None:
    qualified_for_laser = create_soldier(app_session, personal_number="projection-two-tiers-a")
    unqualified = create_soldier(app_session, personal_number="projection-two-tiers-b")
    laser_duty = _duty(
        app_session,
        soldier_id=qualified_for_laser.id,
        required_range_type=RangeType.laser,
        start_date=AS_OF,
    )
    alal_duty = _duty(
        app_session,
        soldier_id=qualified_for_laser.id,
        required_range_type=RangeType.alal,
        start_date=AS_OF,
    )
    another_laser_duty = _duty(
        app_session,
        soldier_id=unqualified.id,
        required_range_type=RangeType.laser,
        start_date=AS_OF,
    )
    _enable_enforcement(app_session)
    app_session.add(
        SoldierRangeQualification(
            soldier_id=qualified_for_laser.id, range_type=RangeType.laser, valid_until=AS_OF
        )
    )
    app_session.commit()

    facts = project_duty_eligibility(
        app_session,
        soldier_ids=[qualified_for_laser.id, unqualified.id],
        duty_ids=[laser_duty.id, alal_duty.id, another_laser_duty.id],
        as_of=AS_OF,
    )

    assert facts[qualified_for_laser.id, laser_duty.id].eligible is True
    assert facts[qualified_for_laser.id, alal_duty.id].eligible is False
    assert facts[unqualified.id, another_laser_duty.id].eligible is False
    assert (
        count_ineligible_soldiers_for_duties(
            app_session,
            soldier_ids=[qualified_for_laser.id, unqualified.id],
            duty_ids=[laser_duty.id, alal_duty.id, another_laser_duty.id],
            as_of=AS_OF,
        )
        == 2
    )


def test_projects_and_counts_only_each_soldiers_own_duty_assignments(
    app_session: Session,
) -> None:
    laser_soldier = create_soldier(app_session, personal_number="projection-own-duty-laser")
    alal_soldier = create_soldier(app_session, personal_number="projection-own-duty-alal")
    laser_duty = _duty(
        app_session,
        soldier_id=laser_soldier.id,
        required_range_type=RangeType.laser,
        start_date=AS_OF,
    )
    alal_duty = _duty(
        app_session,
        soldier_id=alal_soldier.id,
        required_range_type=RangeType.alal,
        start_date=AS_OF,
    )
    _enable_enforcement(app_session)
    app_session.add_all(
        [
            SoldierRangeQualification(
                soldier_id=laser_soldier.id,
                range_type=RangeType.laser,
                valid_until=AS_OF,
            ),
            SoldierRangeQualification(
                soldier_id=alal_soldier.id,
                range_type=RangeType.alal,
                valid_until=AS_OF,
            ),
        ]
    )
    app_session.commit()

    facts = project_duty_eligibility(
        app_session,
        soldier_ids=[laser_soldier.id, alal_soldier.id],
        duty_ids=[laser_duty.id, alal_duty.id],
        as_of=AS_OF,
    )

    assert set(facts) == {
        (laser_soldier.id, laser_duty.id),
        (alal_soldier.id, alal_duty.id),
    }
    assert (
        count_ineligible_soldiers_for_duties(
            app_session,
            soldier_ids=[laser_soldier.id, alal_soldier.id],
            duty_ids=[laser_duty.id, alal_duty.id],
            as_of=AS_OF,
        )
        == 0
    )


def test_project_duty_eligibility_includes_last_qualification_when_ineligible(
    app_session: Session,
) -> None:
    soldier = create_soldier(app_session, personal_number="proj-last-001")
    duty = _duty(
        app_session,
        soldier_id=soldier.id,
        required_range_type=RangeType.alal,
        start_date=date.today() + timedelta(days=5),
    )
    _enable_enforcement(app_session)
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() - timedelta(days=100),
    ))
    app_session.commit()

    facts = project_duty_eligibility(
        app_session, soldier_ids=[soldier.id], duty_ids=[duty.id], as_of=date.today(),
    )
    fact = facts[soldier.id, duty.id]

    assert fact.eligible is False
    assert fact.last_qualification_type == RangeType.laser
    assert fact.last_qualification_date == date.today() - timedelta(days=100)


def test_project_duty_eligibility_last_qualification_none_when_never_qualified(
    app_session: Session,
) -> None:
    soldier = create_soldier(app_session, personal_number="proj-last-002")
    duty = _duty(
        app_session,
        soldier_id=soldier.id,
        required_range_type=RangeType.alal,
        start_date=date.today() + timedelta(days=5),
    )
    _enable_enforcement(app_session)
    app_session.commit()

    facts = project_duty_eligibility(
        app_session, soldier_ids=[soldier.id], duty_ids=[duty.id], as_of=date.today(),
    )
    fact = facts[soldier.id, duty.id]

    assert fact.last_qualification_type is None
    assert fact.last_qualification_date is None
