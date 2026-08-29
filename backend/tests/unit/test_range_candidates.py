from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyManagerScope,
    DutyType,
    ExemptionType,
    PersonalConstraint,
    RangeAssignment,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    Soldier,
    SoldierExemption,
    SoldierRangeQualification,
)
from app.services.range_auto_assign import excluded_candidates, rank_candidates, rank_candidates_with_excluded
from app.services.ranges import RangeValidationError, add_range_assignment, create_range_event
from app.services.settings_loader import set_setting
from tests.helpers import create_duty_location, create_node, create_range_location, create_soldier


def _dm_for(session: Session, node, *, personal_number: str) -> Soldier:
    """A duty manager scoped to `node`, standing in for the commander/DM whose
    authorized scope the candidate pool is now drawn from. Deliberately placed
    outside `node` themselves (hierarchy_node_id=None) so the dm doesn't show up
    as a stray candidate in their own ranked list."""
    dm = create_soldier(session, personal_number=personal_number, role="duty_manager", hierarchy_node_id=None)
    session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    session.commit()
    return dm


def _weapon_duty_type(session: Session, *, node, name: str) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id])
    session.add(dt)
    session.flush()
    return dt


def _event(session: Session, *, required_count: int = 2, reserve_count: int = 1):
    node = create_node(session, level="branch", name="candidates")
    session.add(DutyType(name="weapon candidates", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    dm = _dm_for(session, node, personal_number="cand-dm")
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(session, name="range").id,
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event, dm


def test_ranks_available_soldiers_and_excludes_already_assigned(app_session: Session) -> None:
    node, event, dm = _event(app_session)
    already = create_soldier(app_session, personal_number="cand-assigned", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=already.id, is_reserve=False)
    open_candidate = create_soldier(app_session, personal_number="cand-open", hierarchy_node_id=node.id)

    ranked = rank_candidates(app_session, event=event, user=dm)

    ranked_ids = {c.soldier.id for c in ranked}
    assert already.id not in ranked_ids
    assert open_candidate.id in ranked_ids
    assert all(c.conflict_warning is None for c in ranked)


def test_qualified_soldier_appears_with_no_conflict_warning(app_session: Session) -> None:
    node, event, dm = _event(app_session)
    soldier = create_soldier(app_session, personal_number="cand-qual", hierarchy_node_id=node.id)

    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=event.date + timedelta(days=365), source_range_event_id=None, source_range_assignment_id=None,
    ))
    app_session.commit()

    ranked = rank_candidates(app_session, event=event, user=dm)
    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.conflict_warning is None
    assert mine.reason_code == "qualified"


def test_does_not_write_any_assignment_rows(app_session: Session) -> None:
    node, event, dm = _event(app_session)
    create_soldier(app_session, personal_number="cand-readonly", hierarchy_node_id=node.id)

    rank_candidates(app_session, event=event, user=dm)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    assert remaining == []


def test_candidates_exclude_soldier_outside_scope(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א-outside")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ב-outside")
    _weapon_duty_type(app_session, node=node, name="weapon-a-outside")
    dm = _dm_for(app_session, node, personal_number="6000000")
    outsider = create_soldier(app_session, personal_number="6000001", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert outsider.id not in {c.soldier.id for c in ranked}


def test_candidates_include_soldier_from_sibling_node_in_managers_scope(app_session: Session) -> None:
    """Regression test: a commander/DM whose scope spans a parent unit must be able
    to draw reserve candidates from any sub-unit under it, not only the specific
    sub-unit the range event happens to be tied to — otherwise the reserve pool
    dries up as soon as that one sub-unit's soldiers are all assigned as primaries."""
    parent = create_node(app_session, level="גדוד", name="גדוד היקף")
    event_node = create_node(app_session, level="פלוגה", name="פלוגה מארחת", parent=parent)
    sibling_node = create_node(app_session, level="פלוגה", name="פלוגה שכנה", parent=parent)
    _weapon_duty_type(app_session, node=parent, name="weapon-sibling-scope")
    dm = _dm_for(app_session, parent, personal_number="6000002")
    sibling_soldier = create_soldier(app_session, personal_number="6000003", hierarchy_node_id=sibling_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=event_node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert sibling_soldier.id in {c.soldier.id for c in ranked}


def test_hard_excludes_range_exempt_soldier(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה פטור")
    dm = _dm_for(app_session, node, personal_number="6000003a")
    # No requires_weapon duty type eligible for this node -> soldier is structurally exempt.
    soldier = create_soldier(app_session, personal_number="6000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert soldier.id not in {c.soldier.id for c in ranked}


def test_hard_excludes_soldier_with_weapons_forbidding_exemption_even_with_urgent_duty(app_session: Session) -> None:
    """Exemptions are a hard, permanent eligibility gate — unlike a personal
    constraint or duty-day conflict, an urgent upcoming duty never overrides one."""
    node = create_node(app_session, level="פלוגה", name="פלוגה פטור-דחוף")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-exempt-urgent")
    dm = _dm_for(app_session, node, personal_number="6000003b")
    soldier = create_soldier(app_session, personal_number="6000003c", hierarchy_node_id=node.id)
    location = create_duty_location(app_session)
    urgent_duty_date = date.today() + timedelta(days=5)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=urgent_duty_date, end_date=urgent_duty_date, status="published",
    ))
    exemption_type = ExemptionType(name="פציעה", forbids_weapons=True, is_global=False)
    app_session.add(exemption_type)
    app_session.flush()
    app_session.add(SoldierExemption(
        soldier_id=soldier.id, exemption_type_id=exemption_type.id,
        start_date=date.today(), end_date=None,
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=1), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert soldier.id not in {c.soldier.id for c in ranked}


def test_constrained_soldier_with_no_urgent_duty_gets_unconditional_warning_when_override_allowed(app_session: Session) -> None:
    """Manual override is allowed by default, so an approved personal constraint no
    longer needs a near-term weapon duty to justify keeping the soldier eligible —
    it always surfaces as a conflict_warning."""
    node = create_node(app_session, level="פלוגה", name="פלוגה אילוץ")
    _weapon_duty_type(app_session, node=node, name="weapon-constraint")
    dm = _dm_for(app_session, node, personal_number="6000004a")
    soldier = create_soldier(app_session, personal_number="6000004", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    constraint_start = event_date - timedelta(days=1)
    constraint_end = event_date + timedelta(days=1)
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=constraint_start,
        end_date=constraint_end, reason="חופשה", status="approved",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.conflict_warning == (
        f"אילוץ מאושר {constraint_start.strftime('%d.%m.%Y')}–{constraint_end.strftime('%d.%m.%Y')}"
    )
    assert mine.personal_constraint_conflict is True


def test_constrained_soldier_hard_excluded_when_override_disallowed(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אילוץ ללא-עקיפה")
    _weapon_duty_type(app_session, node=node, name="weapon-constraint-no-override")
    dm = _dm_for(app_session, node, personal_number="6000004f")
    soldier = create_soldier(app_session, personal_number="6000004g", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=event_date - timedelta(days=1),
        end_date=event_date + timedelta(days=1), reason="חופשה", status="approved",
    ))
    set_setting(app_session, "constraints.allow_manual_override", False, actor_id=None)
    app_session.flush()

    ranked, excluded = rank_candidates_with_excluded(app_session, event=event, user=dm)

    assert soldier.id not in {c.soldier.id for c in ranked}
    assert any(e.soldier_id == soldier.id and e.reason == "personal_constraint" for e in excluded)


def test_keeps_constrained_soldier_with_urgent_upcoming_duty_and_shows_conflict_warning(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אילוץ דחוף")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-constraint-urgent")
    dm = _dm_for(app_session, node, personal_number="6000004b")
    soldier = create_soldier(app_session, personal_number="6000004c", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    constraint_start = event_date - timedelta(days=1)
    constraint_end = event_date + timedelta(days=1)
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=constraint_start, end_date=constraint_end,
        reason="חופשה", status="approved",
    ))
    location = create_duty_location(app_session)
    urgent_duty_date = date.today() + timedelta(days=20)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=urgent_duty_date, end_date=urgent_duty_date, status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.conflict_warning == (
        f"אילוץ מאושר {constraint_start.strftime('%d.%m.%Y')}–{constraint_end.strftime('%d.%m.%Y')}"
    )


def test_hard_excludes_soldier_on_duty_that_day_with_no_urgent_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בתורנות")
    location = create_duty_location(app_session)
    # A weapon duty type must exist for the node so the soldier isn't structurally
    # exempt -- the conflicting duty itself is deliberately non-weapon, so it can't
    # double as the "urgent upcoming duty" justification for the override.
    _weapon_duty_type(app_session, node=node, name="weapon-on-duty")
    non_weapon_dt = DutyType(name="שמירה רגילה", score_per_day=Decimal("1.00"), requires_weapon=False)
    app_session.add(non_weapon_dt)
    app_session.flush()
    dm = _dm_for(app_session, node, personal_number="6000005a")
    soldier = create_soldier(app_session, personal_number="6000005", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=non_weapon_dt.id, duty_location_id=location.id,
        start_date=event_date, end_date=event_date + timedelta(days=1), status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert soldier.id not in {c.soldier.id for c in ranked}


def test_keeps_soldier_on_duty_that_day_with_urgent_upcoming_duty_and_shows_conflict_warning(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בתורנות דחופה")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-on-duty-urgent")
    dm = _dm_for(app_session, node, personal_number="6000005b")
    soldier = create_soldier(app_session, personal_number="6000005c", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    conflicting_duty_type = DutyType(name="שמירה", score_per_day=Decimal("1.00"), requires_weapon=False)
    app_session.add(conflicting_duty_type)
    app_session.flush()
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=conflicting_duty_type.id, duty_location_id=location.id,
        start_date=event_date, end_date=event_date + timedelta(days=1), status="published",
    ))
    urgent_duty_date = date.today() + timedelta(days=10)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=urgent_duty_date, end_date=urgent_duty_date, status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.conflict_warning == f"משובץ לתורנות 'שמירה' ב-{event_date.strftime('%d.%m.%Y')}"
    # This warning is a plain duty-conflict notice, not an overridable personal
    # constraint — there is no PersonalConstraint row here, so the frontend must
    # not offer (and the backend must not honor) an override-reason flow for it.
    assert mine.personal_constraint_conflict is False


def test_constrained_soldier_gets_warning_regardless_of_duty_window(app_session: Session) -> None:
    """The NEAR_DUTY_WINDOW_DAYS gate only applies to the duty-conflict-without-
    constraint case now — a personal constraint warns unconditionally (when
    override is allowed) whether or not there's a nearby weapon duty at all."""
    node = create_node(app_session, level="פלוגה", name="פלוגה חלון-זמן")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-window")
    dm = _dm_for(app_session, node, personal_number="6000004d")
    soldier = create_soldier(app_session, personal_number="6000004e", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    constraint_start = event_date - timedelta(days=1)
    constraint_end = event_date + timedelta(days=1)
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=constraint_start,
        end_date=constraint_end, reason="חופשה", status="approved",
    ))
    location = create_duty_location(app_session)
    far_duty_date = date.today() + timedelta(days=31)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=far_duty_date, end_date=far_duty_date, status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.conflict_warning == (
        f"אילוץ מאושר {constraint_start.strftime('%d.%m.%Y')}–{constraint_end.strftime('%d.%m.%Y')}"
    )


def test_does_not_exclude_soldier_when_duty_ends_on_event_date(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה סוף-תורנות-בלעדי")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-duty-exclusive-end")
    dm = _dm_for(app_session, node, personal_number="6000008a")
    soldier = create_soldier(app_session, personal_number="6000008", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date - timedelta(days=1), end_date=event_date, status="published",
    ))
    app_session.flush()

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert soldier.id in {c.soldier.id for c in ranked}


def test_hard_excludes_soldier_at_another_range_same_day_even_with_urgent_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מטווח-אחר")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-other-range")
    dm = _dm_for(app_session, node, personal_number="6000006a")
    soldier = create_soldier(app_session, personal_number="6000006", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח אחר").id, required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=soldier.id, is_reserve=False)
    location = create_duty_location(app_session)
    urgent_duty_date = date.today() + timedelta(days=10)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=urgent_duty_date, end_date=urgent_duty_date, status="published",
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert soldier.id not in {c.soldier.id for c in ranked}


def test_applies_all_eligibility_filters_independently_before_ranking(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה eligibility matrix")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה outside matrix")
    _weapon_duty_type(app_session, node=node, name="weapon-eligibility-matrix")
    dm = _dm_for(app_session, node, personal_number="6000009a")
    duty_location = create_duty_location(app_session)
    event_date = date.today() + timedelta(days=5)
    eligible = create_soldier(app_session, personal_number="6000010", hierarchy_node_id=node.id)
    outside_scope = create_soldier(app_session, personal_number="6000011", hierarchy_node_id=other_node.id)
    constrained = create_soldier(app_session, personal_number="6000012", hierarchy_node_id=node.id)
    on_duty = create_soldier(app_session, personal_number="6000013", hierarchy_node_id=node.id)
    at_another_range = create_soldier(app_session, personal_number="6000014", hierarchy_node_id=node.id)
    app_session.add(PersonalConstraint(
        soldier_id=constrained.id, start_date=event_date, end_date=event_date,
        reason="approved leave", status="approved",
    ))
    # Manual override disallowed so the constraint hard-excludes this soldier,
    # exercising it alongside the other independent hard-exclusion reasons below.
    set_setting(app_session, "constraints.allow_manual_override", False, actor_id=None)
    non_weapon_dt = DutyType(name="שמירה מטריקס", score_per_day=Decimal("1.00"), requires_weapon=False)
    app_session.add(non_weapon_dt)
    app_session.flush()
    app_session.add(DutyAssignment(
        soldier_id=on_duty.id, duty_type_id=non_weapon_dt.id, duty_location_id=duty_location.id,
        start_date=event_date, end_date=event_date + timedelta(days=1), status="published",
    ))
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, range_location_id=create_range_location(app_session, name="another range").id, required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=at_another_range.id, is_reserve=False)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)
    ranked_ids = {c.soldier.id for c in ranked}

    assert eligible.id in ranked_ids
    assert outside_scope.id not in ranked_ids
    assert constrained.id not in ranked_ids
    assert on_duty.id not in ranked_ids
    assert at_another_range.id not in ranked_ids


def test_tier_a_sorts_before_tier_b_before_tier_c_before_tier_d(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה שכבות")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-tiers")
    dm = _dm_for(app_session, node, personal_number="6100000")
    event_date = date.today() + timedelta(days=5)

    tier_d_soldier = create_soldier(app_session, personal_number="6100001", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=tier_d_soldier.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=30),
    ))
    tier_c_soldier = create_soldier(app_session, personal_number="6100002", hierarchy_node_id=node.id)
    tier_b_soldier = create_soldier(app_session, personal_number="6100005", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=tier_b_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date + timedelta(days=1), end_date=event_date + timedelta(days=1), status="published", is_reserve=True,
    ))
    tier_a_soldier = create_soldier(app_session, personal_number="6100003", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=tier_a_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date + timedelta(days=1), end_date=event_date + timedelta(days=1), status="published",
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=4,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    order = [c.soldier.id for c in ranked]
    assert order == [tier_a_soldier.id, tier_b_soldier.id, tier_c_soldier.id, tier_d_soldier.id]


def test_tier_a_orders_by_earliest_duty_start(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-א")
    location = create_duty_location(app_session)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-tier-a-order")
    dm = _dm_for(app_session, node, personal_number="6200000")
    event_date = date.today() + timedelta(days=5)

    later_soldier = create_soldier(app_session, personal_number="6200001", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=later_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=10), status="published",
    ))
    sooner_soldier = create_soldier(app_session, personal_number="6200002", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=sooner_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date + timedelta(days=2), end_date=event_date + timedelta(days=2), status="published",
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    order = [c.soldier.id for c in ranked]
    assert order == [sooner_soldier.id, later_soldier.id]


def test_tier_d_orders_by_soonest_expiring_qualification(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-ד")
    _weapon_duty_type(app_session, node=node, name="weapon-tier-d-order")
    dm = _dm_for(app_session, node, personal_number="6300000")
    event_date = date.today() + timedelta(days=5)

    expires_later = create_soldier(app_session, personal_number="6300001", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=expires_later.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=100),
    ))
    expires_sooner = create_soldier(app_session, personal_number="6300002", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=expires_sooner.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=10),
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    order = [c.soldier.id for c in ranked]
    assert order == [expires_sooner.id, expires_later.id]


def test_qualification_at_higher_range_type_counts_as_tier_d(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה איכות-גבוהה")
    _weapon_duty_type(app_session, node=node, name="weapon-higher-qual")
    dm = _dm_for(app_session, node, personal_number="6400000")
    event_date = date.today() + timedelta(days=5)

    soldier = create_soldier(app_session, personal_number="6400001", hierarchy_node_id=node.id)
    # Qualified at "live" (higher than the event's "laser") -> still Tier D for a laser event.
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.live, valid_until=event_date + timedelta(days=10),
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "qualified"


def test_earlier_primary_range_qualifies_later_candidate_event(app_session: Session) -> None:
    node, event, dm = _event(app_session, required_count=1)
    soldier = create_soldier(app_session, personal_number="sequencing-primary", hierarchy_node_id=node.id)
    earlier_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event.date - timedelta(days=5),
        range_location_id=create_range_location(app_session, name="earlier range").id,
        required_count=1,
    )
    app_session.add(RangeAssignment(
        range_event_id=earlier_event.id, soldier_id=soldier.id, is_reserve=False,
    ))
    app_session.commit()

    mine = next(candidate for candidate in rank_candidates(app_session, event=event, user=dm)
                if candidate.soldier.id == soldier.id)

    assert mine.reason_code == "qualified"
    assert mine.explanation == f"מטווח ראשי תקף עד {(earlier_event.date + timedelta(days=180)).strftime('%d.%m.%Y')}"


def test_primary_coverage_is_stronger_than_reserve_coverage(app_session: Session) -> None:
    node, event, dm = _event(app_session, required_count=2)
    primary = create_soldier(app_session, personal_number="sequencing-primary-kind", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="sequencing-reserve-kind", hierarchy_node_id=node.id)
    earlier_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event.date - timedelta(days=5),
        range_location_id=create_range_location(app_session, name="kind range").id,
        required_count=1,
    )
    app_session.add_all([
        RangeAssignment(range_event_id=earlier_event.id, soldier_id=primary.id, is_reserve=False),
        RangeAssignment(range_event_id=earlier_event.id, soldier_id=reserve.id, is_reserve=True,
                        attendance_status="pending"),
    ])
    app_session.commit()

    ranked = {candidate.soldier.id: candidate for candidate in rank_candidates(app_session, event=event, user=dm)}

    assert ranked[primary.id].reason_code == "qualified"
    assert ranked[reserve.id].reason_code != "qualified"


def test_pending_primary_excusal_makes_range_reserve_like(app_session: Session) -> None:
    node, event, dm = _event(app_session, required_count=1)
    soldier = create_soldier(app_session, personal_number="sequencing-pending", hierarchy_node_id=node.id)
    earlier_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event.date - timedelta(days=5),
        range_location_id=create_range_location(app_session, name="pending range").id,
        required_count=1,
    )
    assignment = RangeAssignment(range_event_id=earlier_event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.flush()
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, range_event_id=earlier_event.id,
        requested_by=None, reason="pending", status=RangeExcusalStatus.pending,
    ))
    app_session.commit()

    mine = next(candidate for candidate in rank_candidates(app_session, event=event, user=dm)
                if candidate.soldier.id == soldier.id)

    assert mine.reason_code != "qualified"


def test_future_range_after_candidate_event_does_not_cover_current_event(app_session: Session) -> None:
    node, event, dm = _event(app_session, required_count=1)
    soldier = create_soldier(app_session, personal_number="sequencing-future", hierarchy_node_id=node.id)
    future_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event.date + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="future range").id,
        required_count=1,
    )
    app_session.add(RangeAssignment(range_event_id=future_event.id, soldier_id=soldier.id, is_reserve=False))
    app_session.commit()

    mine = next(candidate for candidate in rank_candidates(app_session, event=event, user=dm)
                if candidate.soldier.id == soldier.id)

    assert mine.reason_code != "qualified"


def test_candidate_duty_ranking_uses_duties_after_event_and_primary_before_reserve(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="sequencing duties")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="sequencing weapon")
    location = create_duty_location(app_session)
    dm = _dm_for(app_session, node, personal_number="sequencing-duty-dm")
    event_date = date.today() + timedelta(days=5)
    primary = create_soldier(app_session, personal_number="sequencing-duty-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="sequencing-duty-reserve", hierarchy_node_id=node.id)
    app_session.add_all([
        DutyAssignment(
            soldier_id=primary.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=10),
            status="published", is_reserve=False,
        ),
        DutyAssignment(
            soldier_id=primary.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=date.today() + timedelta(days=12), end_date=date.today() + timedelta(days=12),
            status="published", is_reserve=False,
        ),
        DutyAssignment(
            soldier_id=reserve.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=date.today() + timedelta(days=6), end_date=date.today() + timedelta(days=6),
            status="published", is_reserve=True,
        ),
        DutyAssignment(
            soldier_id=reserve.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=date.today() + timedelta(days=8), end_date=date.today() + timedelta(days=8),
            status="published", is_reserve=True,
        ),
    ])
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="duty ranking range").id,
        required_count=2,
    )

    ranked = [candidate.soldier.id for candidate in rank_candidates(app_session, event=event, user=dm)]

    candidates = rank_candidates(app_session, event=event, user=dm)
    assert ranked[:2] == [primary.id, reserve.id]
    primary_candidate = next(candidate for candidate in candidates if candidate.soldier.id == primary.id)
    reserve_candidate = next(candidate for candidate in candidates if candidate.soldier.id == reserve.id)
    assert primary_candidate.explanation.endswith(
        f"{(date.today() + timedelta(days=10)).strftime('%d.%m.%Y')}"
    )
    assert reserve_candidate.explanation.endswith(
        f"{(date.today() + timedelta(days=6)).strftime('%d.%m.%Y')}"
    )


def test_candidate_duty_ranking_ignores_duty_on_or_before_the_range_date(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="candidate duty date boundary")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="candidate duty date boundary weapon")
    location = create_duty_location(app_session)
    dm = _dm_for(app_session, node, personal_number="sequencing-duty-boundary-dm")
    event_date = date.today() + timedelta(days=5)
    soldier = create_soldier(app_session, personal_number="sequencing-duty-boundary", hierarchy_node_id=node.id)
    later_duty_date = event_date + timedelta(days=3)
    app_session.add_all([
        DutyAssignment(
            soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1), status="published",
        ),
        DutyAssignment(
            soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=event_date, end_date=event_date, status="published",
        ),
        DutyAssignment(
            soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
            start_date=later_duty_date, end_date=later_duty_date, status="published",
        ),
    ])
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="candidate duty date boundary range").id,
        required_count=1,
    )

    mine = next(candidate for candidate in rank_candidates(app_session, event=event, user=dm)
                if candidate.soldier.id == soldier.id)

    assert mine.reason_code == "duty_priority"
    assert mine.explanation == f"תורנות קרובה ב-{later_duty_date.strftime('%d.%m.%Y')}"


def test_reason_code_available_and_balanced_when_no_qualification_or_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת סיבת שיבוץ")
    _weapon_duty_type(app_session, node=node, name="תורנות נשק סיבת שיבוץ")
    dm = _dm_for(app_session, node, personal_number="7010000")
    soldier = create_soldier(app_session, personal_number="7010001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "available_and_balanced"
    assert mine.explanation == "מעולם לא ביצע מטווחים"


def test_reason_code_duty_priority_for_future_regular_weapon_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת עדיפות נשק")
    dm = _dm_for(app_session, node, personal_number="7010003")
    soldier = create_soldier(app_session, personal_number="7010004", hierarchy_node_id=node.id)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="תורנות נשק עדיפות")
    location = create_duty_location(app_session)
    future_duty_date = date.today() + timedelta(days=7)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=future_duty_date, end_date=future_duty_date, status="published",
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "duty_priority"
    assert mine.explanation == f"תורנות קרובה ב-{future_duty_date.strftime('%d.%m.%Y')}"


def test_reason_code_reserve_duty_priority_for_future_reserve_weapon_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת עדיפות רזרבה")
    dm = _dm_for(app_session, node, personal_number="7010005")
    soldier = create_soldier(app_session, personal_number="7010006", hierarchy_node_id=node.id)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="תורנות רזרבה עדיפות")
    location = create_duty_location(app_session)
    future_duty_date = date.today() + timedelta(days=8)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=future_duty_date, end_date=future_duty_date, status="published", is_reserve=True,
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "reserve_duty_priority"
    assert mine.explanation == f"תורנות רזרבה קרובה ב-{future_duty_date.strftime('%d.%m.%Y')}"


def test_candidate_ranking_ignores_urgent_duty_needing_a_different_range_tier(app_session: Session) -> None:
    """A soldier's upcoming duty must only boost their priority for a range event
    whose range_type it actually needs — an urgent laser-tier duty must not make
    a soldier look urgent for an alal event. Both soldiers here are structurally
    eligible for the alal event via the alal-tier duty type being in scope at
    their node (eligibility is about the duty type's scope, not who's actually
    assigned to it) — isolating this test to ranking priority, not the hard gate."""
    node = create_node(app_session, level="פלוגה", name="פלוגת עדיפות לפי סוג מטווח")
    dm = _dm_for(app_session, node, personal_number="7020001")
    laser_duty = DutyType(
        name="שמירה לייזר עדיפות מטווח", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    alal_duty = DutyType(
        name='הגנ"ש עדיפות מטווח', score_per_day=Decimal("1.00"),
        requires_weapon=False, required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    )
    app_session.add_all([laser_duty, alal_duty])
    app_session.flush()
    location = create_duty_location(app_session)

    off_tier_soldier = create_soldier(app_session, personal_number="7020002", hierarchy_node_id=node.id)
    on_tier_soldier = create_soldier(app_session, personal_number="7020003", hierarchy_node_id=node.id)
    future_duty_date = date.today() + timedelta(days=7)
    app_session.add_all([
        DutyAssignment(
            soldier_id=off_tier_soldier.id, duty_type_id=laser_duty.id, duty_location_id=location.id,
            start_date=future_duty_date, end_date=future_duty_date, status="published",
        ),
        DutyAssignment(
            soldier_id=on_tier_soldier.id, duty_type_id=alal_duty.id, duty_location_id=location.id,
            start_date=future_duty_date, end_date=future_duty_date, status="published",
        ),
    ])
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.alal,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="מטווח עדיפות אלל").id,
        required_count=2,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    off_tier_candidate = next(c for c in ranked if c.soldier.id == off_tier_soldier.id)
    on_tier_candidate = next(c for c in ranked if c.soldier.id == on_tier_soldier.id)
    assert off_tier_candidate.reason_code == "available_and_balanced"
    assert on_tier_candidate.reason_code == "duty_priority"


def test_regular_duty_outranks_reserve_duty(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת עדיפות משולבת")
    dm = _dm_for(app_session, node, personal_number="7010007")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="תורנות משולבת")
    location = create_duty_location(app_session)

    reserve_soldier = create_soldier(app_session, personal_number="7010008", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=reserve_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=6), end_date=date.today() + timedelta(days=6),
        status="published", is_reserve=True,
    ))
    regular_soldier = create_soldier(app_session, personal_number="7010009", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=regular_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=20), end_date=date.today() + timedelta(days=20),
        status="published", is_reserve=False,
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    order = [c.soldier.id for c in ranked]
    # Regular duty (rank 0) sorts before reserve duty (rank 1), even though the
    # reserve soldier's duty date is sooner.
    assert order == [regular_soldier.id, reserve_soldier.id]


def test_explanation_shows_last_valid_until_when_previously_qualified(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת פג תוקף")
    _weapon_duty_type(app_session, node=node, name="תורנות פג תוקף")
    dm = _dm_for(app_session, node, personal_number="7010010")
    soldier = create_soldier(app_session, personal_number="7010011", hierarchy_node_id=node.id)
    expired_until = date.today() - timedelta(days=30)
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser, valid_until=expired_until,
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.reason_code == "available_and_balanced"
    assert mine.explanation == f"אין מטווחים בתוקף מ-{expired_until.strftime('%d.%m.%Y')}"


def test_excluded_candidates_reports_reasons_and_omits_them_from_ranking(app_session: Session) -> None:
    """A weapon-exempt soldier, a structurally-ineligible soldier, and a soldier
    already assigned to another range the same day should each show up in
    `excluded_candidates` with the matching reason code, and none of them should
    appear in `rank_candidates`'s eligible/ranked list."""
    node = create_node(app_session, level="פלוגה", name="פלוגה סיבות החרגה")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה בלי כשירות נשק")
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-excluded-reasons")
    dm = _dm_for(app_session, node, personal_number="8000000")
    event_date = date.today() + timedelta(days=5)

    exempt_soldier = create_soldier(app_session, personal_number="8000001", hierarchy_node_id=node.id)
    exemption_type = ExemptionType(name="פציעה קבועה", forbids_weapons=True, is_global=False)
    app_session.add(exemption_type)
    app_session.flush()
    app_session.add(SoldierExemption(
        soldier_id=exempt_soldier.id, exemption_type_id=exemption_type.id,
        start_date=date.today(), end_date=None,
    ))

    # No requires_weapon duty type is eligible for other_node -> structurally exempt.
    structurally_ineligible_soldier = create_soldier(app_session, personal_number="8000002", hierarchy_node_id=other_node.id)
    # Extend the dm's scope to cover other_node too, so this soldier is in the pool at all.
    session_dm_scope = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=other_node.id)
    app_session.add(session_dm_scope)

    elsewhere_soldier = create_soldier(app_session, personal_number="8000003", hierarchy_node_id=node.id)
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח אחר-החרגה").id,
        required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=elsewhere_soldier.id, is_reserve=False)

    eligible_soldier = create_soldier(app_session, personal_number="8000004", hierarchy_node_id=node.id)
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח סיבות החרגה").id,
        required_count=1,
    )

    ranked, excluded = rank_candidates_with_excluded(app_session, event=event, user=dm)

    ranked_ids = {c.soldier.id for c in ranked}
    reasons_by_id = {x.soldier_id: x.reason for x in excluded}

    assert eligible_soldier.id in ranked_ids
    assert exempt_soldier.id not in ranked_ids
    assert structurally_ineligible_soldier.id not in ranked_ids
    assert elsewhere_soldier.id not in ranked_ids

    assert reasons_by_id[exempt_soldier.id] == "weapon_exempt"
    assert reasons_by_id[structurally_ineligible_soldier.id] == "structurally_ineligible"
    assert reasons_by_id[elsewhere_soldier.id] == "assigned_elsewhere_same_day"
    assert eligible_soldier.id not in reasons_by_id


def test_candidates_exclude_soldier_needing_only_a_lower_range_tier_from_alal_event(app_session: Session) -> None:
    """A soldier whose only duty type requires laser must be structurally
    ineligible for an alal event, even though they're a normal weapon-carrying
    soldier for laser/live purposes — attending alal isn't relevant to them."""
    node = create_node(app_session, level="פלוגה", name="פלוגת לייזר בלבד מועמדים")
    dm = _dm_for(app_session, node, personal_number="7030001")
    laser_only_soldier = create_soldier(app_session, personal_number="7030002", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="שמירה לייזר מועמדים בלבד", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.alal,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="מטווח אלל מועמדים").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)
    excluded = excluded_candidates(app_session, event=event, user=dm)

    assert laser_only_soldier.id not in {c.soldier.id for c in ranked}
    reasons_by_id = {x.soldier_id: x.reason for x in excluded}
    assert reasons_by_id[laser_only_soldier.id] == "structurally_ineligible"


def test_add_range_assignment_rejects_soldier_needing_only_a_lower_range_tier_for_alal_event(
    app_session: Session,
) -> None:
    """Direct regression test for the reported bug: the write path itself
    (not just the candidate list) must reject assigning a soldier to an alal
    event when their only duty type needs a lower tier."""
    node = create_node(app_session, level="פלוגה", name="פלוגת דחיית שיבוץ אלל")
    laser_only_soldier = create_soldier(app_session, personal_number="7030005", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="שמירה לייזר דחיית שיבוץ", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.alal,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="מטווח אלל דחיית שיבוץ").id, required_count=1,
    )

    with pytest.raises(RangeValidationError, match="soldier_range_exempt"):
        add_range_assignment(app_session, event=event, soldier_id=laser_only_soldier.id, is_reserve=False)


def test_candidates_include_soldier_needing_alal_for_alal_event(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת הגנש מועמדים")
    dm = _dm_for(app_session, node, personal_number="7030003")
    alal_soldier = create_soldier(app_session, personal_number="7030004", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name='הגנ"ש מועמדים בדיקה', score_per_day=Decimal("1.00"),
        requires_weapon=False, required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.alal,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="מטווח אלל מועמדים ב").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=dm)

    assert alal_soldier.id in {c.soldier.id for c in ranked}


def test_admin_sees_soldiers_across_the_whole_tree(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אדמין")
    _weapon_duty_type(app_session, node=node, name="weapon-admin-scope")
    admin = create_soldier(app_session, personal_number="7020000", role="admin")
    soldier = create_soldier(app_session, personal_number="7020001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=1,
    )

    ranked = rank_candidates(app_session, event=event, user=admin)

    assert soldier.id in {c.soldier.id for c in ranked}
