from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import (
    DutyType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.ranges import add_range_assignment, cancel_range_event, create_range_event, mark_attendance
from app.services.settings_loader import set_setting
from app.services.weapon_eligibility import (
    _latest_qualification_by_soldier,
    bulk_ineligible_duty_blocks,
    compute_eligibility,
)
from tests.helpers import create_node, create_range_location, create_soldier


def _make_weapon_eligible(session: Session, node_id) -> None:
    """`add_range_assignment` rejects soldiers who are structurally exempt from
    weapons (no requires_weapon=True DutyType in scope) -- see
    app.services.range_exemption.is_range_exempt. The brief's test bodies assume
    the soldier's node has a weapon-carrying duty type, matching the pattern used
    in tests/unit/test_ranges_service.py::test_add_range_assignment_success."""
    session.add(DutyType(
        name=f"weapon-duty-{node_id}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node_id],
    ))
    session.flush()


def _enable_mitvachim(session: Session) -> None:
    """Weapon-qualification enforcement is gated on the ranges module (מטווחים)
    itself being on -- see weapon_eligibility._enforce_enabled. Tests that
    exercise enforcement must opt in explicitly; mitvachim.enabled defaults to
    False (row absent in the test DB, same fallback as production)."""
    set_setting(session, "mitvachim.enabled", True, actor_id=None)


def test_none_required_type_is_always_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-001")
    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=None, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_current_qualification_covers_as_of_date(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-002")
    _enable_mitvachim(app_session)
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=10),
    )
    assert eligible is True
    assert reason is None


def test_expired_qualification_is_not_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-003")
    _enable_mitvachim(app_session)
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() - timedelta(days=1),
    ))
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=date.today()
    )
    assert eligible is False
    assert reason == "weapon_qualification"


def test_future_scheduled_range_grants_eligibility_on_and_after_its_date(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-1")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    # Before the range: not yet eligible via this future assignment.
    too_early, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=4),
    )
    assert too_early is False

    # On/after the range date, within its projected validity window (180 days for laser).
    on_time, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=5),
    )
    assert on_time is True
    assert reason is None


def test_reserve_assignment_does_not_grant_eligibility(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-2")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-005", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1, reserve_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_pending_excusal_disqualifies_future_range_by_default(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-3")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-006", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, requested_by=soldier.id,
        reason="בדיקה", status=RangeExcusalStatus.pending,
    ))
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_pending_excusal_setting_off_keeps_future_range_eligible(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-4")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-007", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, requested_by=soldier.id,
        reason="בדיקה", status=RangeExcusalStatus.pending,
    ))
    set_setting(app_session, "weapon_qualification.pending_excusal_disqualifies", False, actor_id=None)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is True


def test_lower_tier_range_does_not_satisfy_higher_requirement(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-5")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-008", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False
    assert reason == "weapon_qualification"


def test_master_toggle_off_makes_everyone_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-009")
    _enable_mitvachim(app_session)
    set_setting(app_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_bulk_matches_single_soldier_result(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-6")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    qualified = create_soldier(app_session, personal_number="we-010", hierarchy_node_id=node.id)
    unqualified = create_soldier(app_session, personal_number="we-011", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=qualified.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    block = DutyBlock(
        id=__import__("uuid").uuid4(), duty_type_id=__import__("uuid").uuid4(),
        duty_location_id=__import__("uuid").uuid4(),
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1),
        score_per_day=Decimal("1.00"), required_range_type=RangeType.laser,
    )
    result = bulk_ineligible_duty_blocks(
        app_session, soldier_ids=[qualified.id, unqualified.id], duties=[block]
    )
    assert qualified.id not in result or block.id not in result.get(qualified.id, set())
    assert block.id in result.get(unqualified.id, set())


def test_bulk_ineligible_duty_blocks_excludes_alal_duties(app_session: Session) -> None:
    """אל"ל eligibility is reactive (warning-only) -- it must never surface as a
    hard block from bulk_ineligible_duty_blocks, unlike live/laser."""
    node = create_node(app_session, level="branch", name="we-node-alal")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-016", hierarchy_node_id=node.id)
    app_session.commit()

    alal_block = DutyBlock(
        id=__import__("uuid").uuid4(), duty_type_id=__import__("uuid").uuid4(),
        duty_location_id=__import__("uuid").uuid4(),
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1),
        score_per_day=Decimal("1.00"), required_range_type=RangeType.alal,
    )
    laser_block = DutyBlock(
        id=__import__("uuid").uuid4(), duty_type_id=__import__("uuid").uuid4(),
        duty_location_id=__import__("uuid").uuid4(),
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1),
        score_per_day=Decimal("1.00"), required_range_type=RangeType.laser,
    )

    result = bulk_ineligible_duty_blocks(
        app_session, soldier_ids=[soldier.id], duties=[alal_block, laser_block],
    )

    # Soldier has no qualifications at all -- ineligible for both by the raw
    # data, but only the laser (non-alal) block should surface as a hard
    # block. The alal block must never appear.
    assert alal_block.id not in result.get(soldier.id, set())
    assert laser_block.id in result.get(soldier.id, set())


def test_bulk_ineligible_duty_blocks_include_alal_restores_alal_block(app_session: Session) -> None:
    """The advisory manual-assign-modal candidates endpoint (routes/shifts.py)
    passes include_alal=True to keep showing the אל"ל warning marker to a human
    before they manually assign someone -- unlike the algorithm bridge's hard
    exclusion, this is never a scheduling block. include_alal=True must restore
    the אל"ל block id in the result."""
    node = create_node(app_session, level="branch", name="we-node-alal-include")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-017", hierarchy_node_id=node.id)
    app_session.commit()

    alal_block = DutyBlock(
        id=__import__("uuid").uuid4(), duty_type_id=__import__("uuid").uuid4(),
        duty_location_id=__import__("uuid").uuid4(),
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1),
        score_per_day=Decimal("1.00"), required_range_type=RangeType.alal,
    )

    result = bulk_ineligible_duty_blocks(
        app_session, soldier_ids=[soldier.id], duties=[alal_block], include_alal=True,
    )

    assert alal_block.id in result.get(soldier.id, set())


def test_mitvachim_disabled_makes_everyone_eligible_regardless_of_enforce_setting(app_session: Session) -> None:
    """Finding 1 (Critical): the ranges module (מטווחים) defaults to OFF, and every
    requires_weapon=True DutyType was backfilled with a required_range_type by the
    migration. If enforcement applied while מטווחים is off, no soldier could ever
    satisfy it (no qualification rows, no range events) -- silently blocking every
    weapon duty. So the weapon-qualification check must not apply at all while
    mitvachim.enabled is off, even if weapon_qualification.enforce_eligibility is
    explicitly True."""
    soldier = create_soldier(app_session, personal_number="we-012")
    # mitvachim.enabled left unset -> defaults to False, same as production.
    set_setting(app_session, "weapon_qualification.enforce_eligibility", True, actor_id=None)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=date.today()
    )
    assert eligible is True
    assert reason is None

    # Explicitly setting mitvachim.enabled=False makes the same point without
    # relying on the absent-row fallback.
    set_setting(app_session, "mitvachim.enabled", False, actor_id=None)
    app_session.commit()
    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_cancelled_range_event_does_not_grant_eligibility(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-7")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-013", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    cancel_range_event(app_session, event=event, reason="בדיקה", actor_id=None)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_draft_assignment_does_not_grant_eligibility(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-8")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-014", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    assignment.is_draft = True
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_past_no_show_does_not_grant_eligibility(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-9")
    _make_weapon_eligible(app_session, node.id)
    _enable_mitvachim(app_session)
    soldier = create_soldier(app_session, personal_number="we-015", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() - timedelta(days=1),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="לא הגיע",
    )
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today(),
    )
    assert eligible is False


def test_latest_qualification_by_soldier_ignores_validity_and_picks_max(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="latest-001")
    app_session.add_all([
        SoldierRangeQualification(
            soldier_id=soldier.id, range_type=RangeType.laser,
            valid_until=date.today() - timedelta(days=400),  # expired
        ),
        SoldierRangeQualification(
            soldier_id=soldier.id, range_type=RangeType.live,
            valid_until=date.today() - timedelta(days=10),  # expired, but most recent
        ),
    ])
    app_session.commit()

    result = _latest_qualification_by_soldier(app_session, soldier_ids=[soldier.id])

    assert result[soldier.id] == (RangeType.live, date.today() - timedelta(days=10))


def test_latest_qualification_by_soldier_returns_none_for_soldier_with_no_rows(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="latest-002")
    app_session.commit()

    result = _latest_qualification_by_soldier(app_session, soldier_ids=[soldier.id])

    assert result[soldier.id] is None
