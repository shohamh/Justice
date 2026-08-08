from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
from app.services.duty_config import update_duty_type
from app.services.settings_loader import apply_settings, set_setting, weapon_enforcement_changed
from tests.helpers import create_node, create_soldier


def _make_weapon_assignment(session, *, soldier_id, duty_type, start_date) -> DutyAssignment:
    loc = DutyLocation(name="broad-loc")
    session.add(loc)
    session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id, duty_location_id=loc.id,
        start_date=start_date, end_date=start_date, required_count=1, status="active",
    )
    session.add(shift)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=duty_type.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=start_date, end_date=start_date,
        status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_changing_required_range_type_triggers_recheck_for_that_duty_type(app_session: Session) -> None:
    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="broad-node-1")
    soldier = create_soldier(app_session, personal_number="broad-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, duty_type=dt, start_date=date.today() + timedelta(days=5),
    )
    assert assignment.weapon_ineligible is False

    update_duty_type(
        app_session, duty_type=dt, name=None, score_per_day=None, description=None,
        required_range_type=RangeType.alal,
    )
    app_session.commit()

    from app.services.duty_eligibility_watch import recheck_assignments
    from sqlalchemy import select
    ids = app_session.execute(
        select(DutyAssignment.id).where(DutyAssignment.duty_type_id == dt.id, DutyAssignment.status == "published")
    ).scalars().all()
    recheck_assignments(app_session, ids)
    app_session.refresh(assignment)
    assert assignment.weapon_ineligible is True


def test_update_duty_type_route_triggers_recheck_automatically(app_session: Session) -> None:
    """Unlike the test above (which calls the service function directly and
    manually invokes recheck_assignments), this exercises the actual route-level
    hook added in duty_config.py's update_duty_type: hitting the route function
    itself must trigger the recheck with no manual call."""
    from app.routes.duty_config import UpdateDutyTypeRequest, update_duty_type as route_update_duty_type

    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="broad-node-route")
    user = create_soldier(app_session, personal_number="broad-admin-1", role="admin", hierarchy_node_id=node.id)
    soldier = create_soldier(app_session, personal_number="broad-sol-route", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-route", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, duty_type=dt, start_date=date.today() + timedelta(days=5),
    )
    assert assignment.weapon_ineligible is False

    body = UpdateDutyTypeRequest(required_range_type=RangeType.alal)
    route_update_duty_type(dt.id, body, session=app_session, user=user)

    app_session.refresh(assignment)
    assert assignment.weapon_ineligible is True



def test_update_duty_type_route_clears_required_range_type_and_stale_cache(app_session: Session) -> None:
    from app.routes.duty_config import UpdateDutyTypeRequest, update_duty_type as route_update_duty_type

    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="broad-node-clear")
    user = create_soldier(app_session, personal_number="broad-admin-clear", role="admin", hierarchy_node_id=node.id)
    soldier = create_soldier(app_session, personal_number="broad-sol-clear", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-clear", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, duty_type=dt, start_date=date.today() + timedelta(days=5),
    )
    assignment.weapon_ineligible = True
    assignment.weapon_ineligible_reason = "stale"
    app_session.commit()

    body = UpdateDutyTypeRequest(required_range_type=None)
    route_update_duty_type(dt.id, body, session=app_session, user=user)

    app_session.refresh(dt)
    app_session.refresh(assignment)
    assert dt.required_range_type is None
    assert assignment.weapon_ineligible is False
    assert assignment.weapon_ineligible_reason is None


def test_update_duty_type_route_omitted_range_type_preserves_value(app_session: Session) -> None:
    from app.routes.duty_config import UpdateDutyTypeRequest, update_duty_type as route_update_duty_type

    node = create_node(app_session, level="branch", name="broad-node-omitted")
    user = create_soldier(app_session, personal_number="broad-admin-omitted", role="admin", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-omitted", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    body = UpdateDutyTypeRequest(name="broad-weapon-omitted-renamed")
    route_update_duty_type(dt.id, body, session=app_session, user=user)

    app_session.refresh(dt)
    assert dt.required_range_type == RangeType.laser
def test_update_duty_type_route_no_op_when_range_type_unchanged(app_session: Session) -> None:
    """The hook must not fire (and must not error) when required_range_type is
    omitted or set to the same value it already had."""
    from app.routes.duty_config import UpdateDutyTypeRequest, update_duty_type as route_update_duty_type

    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="broad-node-noop")
    user = create_soldier(app_session, personal_number="broad-admin-noop", role="admin", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-noop", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    body = UpdateDutyTypeRequest(name="broad-weapon-noop-renamed")
    route_update_duty_type(dt.id, body, session=app_session, user=user)
    app_session.refresh(dt)
    assert dt.name == "broad-weapon-noop-renamed"
    assert dt.required_range_type == RangeType.laser


def test_apply_settings_detects_enforce_eligibility_key_change() -> None:
    current = {"weapon_qualification.enforce_eligibility": True}
    updates = {"weapon_qualification.enforce_eligibility": False}
    assert "weapon_qualification.enforce_eligibility" in updates
    assert current.get("weapon_qualification.enforce_eligibility") != updates.get("weapon_qualification.enforce_eligibility")
    assert weapon_enforcement_changed(current, updates) is True
    assert weapon_enforcement_changed(current, {}) is False
    assert weapon_enforcement_changed(current, {"weapon_qualification.enforce_eligibility": True}) is False


def test_update_settings_route_triggers_recheck_when_enforce_eligibility_changes(app_session: Session) -> None:
    """Exercises the actual route-level hook in system_settings.py's
    update_settings: apply_settings itself doesn't commit (its caller does), so
    the trigger lives in the route, after the commit."""
    from app.routes.system_settings import UpdateSettingsBody, update_settings as route_update_settings

    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    set_setting(app_session, "weapon_qualification.enforce_eligibility", True, actor_id=None)
    app_session.commit()

    node = create_node(app_session, level="branch", name="broad-node-settings")
    user = create_soldier(app_session, personal_number="broad-admin-settings", role="admin", hierarchy_node_id=node.id)
    soldier = create_soldier(app_session, personal_number="broad-sol-settings", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-settings", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, duty_type=dt, start_date=date.today() + timedelta(days=5),
    )
    assert assignment.weapon_ineligible is False

    # Flip enforce_eligibility off -> no weapon requirement is enforced any
    # more, so a previously-eligible-with-no-range-cert soldier is unaffected
    # here; instead, flip it back on after seeding a stale ineligible cache to
    # prove the recheck actually runs and clears it (a False starting point
    # would just stay False regardless of whether the hook fired).
    assignment.weapon_ineligible = True
    assignment.weapon_ineligible_reason = "stale"
    app_session.commit()

    body = UpdateSettingsBody(settings={"weapon_qualification.enforce_eligibility": False})
    route_update_settings(body, session=app_session, user=user)

    app_session.refresh(assignment)
    assert assignment.weapon_ineligible is False
