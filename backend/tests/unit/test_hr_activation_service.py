from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import SoldierActivationCode, SoldierHrProfile
from app.services.hr_activation import (
    ActivationCodeError,
    can_generate_activation_code,
    consume_activation_code,
    generate_activation_code,
)
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_soldier


def _hr_linked_soldier(session, *, personal_number: str, hierarchy_node_id=None):
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=hierarchy_node_id)
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.commit()
    return soldier


def test_admin_can_generate_code_for_hr_linked_soldier(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-1", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-1")

    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    assert code.soldier_id == target.id
    assert len(code.code) == 8
    assert code.code.isupper() or code.code.isdigit() or code.code.isalnum()
    assert code.used_at is None
    assert code.created_by == admin.id


def test_commander_at_configured_level_with_scope_can_generate(admin_session):
    node = create_node(admin_session, level="group", name="hract_mador")
    commander = create_soldier(admin_session, personal_number="hract-cmd-1", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-2", hierarchy_node_id=node.id)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is True
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=commander)
    admin_session.commit()
    assert code.soldier_id == target.id


def test_commander_below_configured_level_cannot_generate(admin_session):
    node = create_node(admin_session, level="team", name="hract_team")
    commander = create_soldier(admin_session, personal_number="hract-cmd-2", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-3", hierarchy_node_id=node.id)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is False
    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=commander)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "forbidden"


def test_commander_outside_scope_cannot_generate(admin_session):
    node_a = create_node(admin_session, level="group", name="hract_mador_a")
    node_b = create_node(admin_session, level="group", name="hract_mador_b")
    commander = create_soldier(admin_session, personal_number="hract-cmd-3", role="commander", hierarchy_node_id=node_a.id)
    node_a.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-4", hierarchy_node_id=node_b.id)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is False


def test_generate_rejects_soldier_with_no_hr_profile(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-2", role="admin")
    target = create_soldier(admin_session, personal_number="hract-target-5")

    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "not_hr_linked"


def test_generate_rejects_already_onboarded_soldier(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-3", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-6")
    target.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()

    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "already_activated"


def test_generate_invalidates_prior_unused_code(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-4", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-7")

    first = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()
    first_code = first.code

    second = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    admin_session.refresh(first)
    assert first.used_at is not None
    assert second.used_at is None
    assert second.code != first_code


def test_generate_uses_configured_expiry_days_setting(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-5", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-8")
    set_setting(admin_session, "hr_activation.code_expiry_days", 30, actor_id=None)
    admin_session.commit()

    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    delta = code.expires_at - datetime.now(tz=timezone.utc)
    assert 29 <= delta.days <= 30


def test_consume_activation_code_success(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-6", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-9")
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    consumed = consume_activation_code(admin_session, soldier_id=target.id, code=code.code)
    admin_session.commit()

    assert consumed is True
    admin_session.refresh(code)
    assert code.used_at is not None


def test_consume_activation_code_wrong_code_fails(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-7", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-10")
    generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=target.id, code="WRONGCOD") is False


def test_consume_activation_code_expired_fails(admin_session):
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-11")
    admin_session.add(SoldierActivationCode(
        soldier_id=target.id, code="EXPIRED1",
        expires_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
    ))
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=target.id, code="EXPIRED1") is False


def test_consume_activation_code_already_used_fails(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-8", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-12")
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()
    consume_activation_code(admin_session, soldier_id=target.id, code=code.code)
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=target.id, code=code.code) is False


def test_consume_activation_code_wrong_soldier_fails(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-9", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-13")
    other = _hr_linked_soldier(admin_session, personal_number="hract-target-14")
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=other.id, code=code.code) is False
