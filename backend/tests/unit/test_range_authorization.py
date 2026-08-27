from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.authz import Action, can, is_commander, is_duty_manager, scope_root_ids
from app.services.authority import range_attendance_edit_authorized
from app.services.settings_loader import apply_settings, get_setting
from tests.helpers import create_node, create_soldier


def _can(session: Session, user, action: str, *, target_node) -> bool:
    """Local helper mirroring how routes call `can()`: it takes no session and
    needs roots/is_commander/is_duty_manager computed by the caller."""
    roots = scope_root_ids(session, user)
    return can(
        user,
        action,
        target_node=target_node,
        roots=roots,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    )


def test_range_manage_allowed_for_dm_in_scope(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="פלוגה א")
    dm = create_soldier(app_session, personal_number="3000001", role="duty_manager", hierarchy_node_id=node.id)

    assert _can(app_session, dm, Action.RANGE_MANAGE, target_node=node) is True


def test_range_manage_denied_for_dm_out_of_scope(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="פלוגה ב")
    other_node = create_node(app_session, level="branch", name="פלוגה ג")
    dm = create_soldier(app_session, personal_number="3000002", role="duty_manager", hierarchy_node_id=node.id)

    assert _can(app_session, dm, Action.RANGE_MANAGE, target_node=other_node) is False

def test_range_excusal_decide_allowed_for_dm_in_scope(app_session: Session) -> None:
    """Removing the action from the DM bucket must deny the decision route."""
    node = create_node(app_session, level="branch", name="פלוגת פטורים")
    dm = create_soldier(app_session, personal_number="3000006", role="duty_manager", hierarchy_node_id=node.id)

    assert _can(app_session, dm, Action.RANGE_EXCUSAL_DECIDE, target_node=node) is True


def test_range_excusal_decide_allowed_for_commander_in_scope(app_session: Session) -> None:
    """Removing the action from the commander bucket must deny in-scope review."""
    node = create_node(app_session, level="group", name="מדור פטורים")
    commander = create_soldier(app_session, personal_number="3000007", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    app_session.flush()

    assert _can(app_session, commander, Action.RANGE_EXCUSAL_DECIDE, target_node=node) is True


def test_range_excusal_commander_threshold_defaults_to_mador(app_session: Session) -> None:
    """Changing the migration seed would lower or raise the server-side approval gate.
    "group" is the seeded key for the מדור level — get_level_rank matches
    HierarchyLevelType.key, not .label."""
    assert get_setting(app_session, "mitvachim.excusal_approve_min_commander_level") == "group"


def test_range_attendance_edit_authorized_for_dm_at_required_level(app_session: Session) -> None:
    battalion = create_node(app_session, level="unit", name="גדוד 1")
    company = create_node(app_session, level="branch", name="ענף 1", parent=battalion)
    apply_settings(app_session, {}, {"mitvachim.attendance_edit_min_level": "branch"}, actor_id=None)
    dm = create_soldier(app_session, personal_number="3000003", role="duty_manager", hierarchy_node_id=company.id)

    assert range_attendance_edit_authorized(app_session, user=dm, target_node=company) is True


def test_range_attendance_edit_denied_for_dm_below_required_level(app_session: Session) -> None:
    battalion = create_node(app_session, level="unit", name="גדוד 2")
    company = create_node(app_session, level="branch", name="ענף 2", parent=battalion)
    platoon = create_node(app_session, level="group", name="פלוגה 2", parent=company)
    apply_settings(app_session, {}, {"mitvachim.attendance_edit_min_level": "branch"}, actor_id=None)
    dm = create_soldier(app_session, personal_number="3000004", role="duty_manager", hierarchy_node_id=platoon.id)

    assert range_attendance_edit_authorized(app_session, user=dm, target_node=platoon) is False


def test_range_attendance_edit_denied_for_commander_regardless_of_level(app_session: Session) -> None:
    battalion = create_node(app_session, level="unit", name="גדוד 3")
    company = create_node(app_session, level="branch", name="ענף 3", parent=battalion)
    apply_settings(app_session, {}, {"mitvachim.attendance_edit_min_level": "branch"}, actor_id=None)
    commander = create_soldier(app_session, personal_number="3000005", role="commander", hierarchy_node_id=company.id)
    company.commander_id = commander.id
    app_session.flush()

    assert range_attendance_edit_authorized(app_session, user=commander, target_node=company) is False
