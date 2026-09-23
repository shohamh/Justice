from __future__ import annotations

import uuid
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


def _hr_linked_soldier(session, *, personal_number: str, hierarchy_node_id=None, must_change_password: bool = True):
    # must_change_password=True by default: mirrors a real HR-synced soldier,
    # who never had a real password yet — that's exactly the population
    # eligible for a fresh activation code (see generate_activation_code's
    # must_change_password check, closing the C2 impersonation finding).
    soldier = create_soldier(
        session, personal_number=personal_number, hierarchy_node_id=hierarchy_node_id,
        must_change_password=must_change_password,
    )
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


def test_generate_rejects_soldier_with_real_password_already(admin_session):
    """C2: a soldier with must_change_password=False already has a real,
    working password — a pre-existing soldier later linked to an HR profile,
    or one who already activated via a code and changed their password.
    Neither should be eligible for a fresh code, which would otherwise let
    anyone with scope silently mint credentials that log in as them."""
    admin = create_soldier(admin_session, personal_number="hract-admin-11", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-18", must_change_password=False)

    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "already_activated"


def test_generate_rejects_soldier_who_already_changed_password_after_activation(admin_session):
    """The exact C1/C2 interaction: soldier activates via code, changes their
    password (must_change_password flips back to False), then a commander
    tries to mint a fresh code for them — must stay blocked."""
    admin = create_soldier(admin_session, personal_number="hract-admin-12", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-19", must_change_password=True)
    target.must_change_password = False
    admin_session.commit()

    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "already_activated"


def test_generate_writes_audit_row(admin_session):
    from sqlalchemy import text

    admin = create_soldier(admin_session, personal_number="hract-admin-13", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-20")

    generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    rows = admin_session.execute(
        text(
            "SELECT actor_id, entity_id FROM audit_log WHERE action='hr_activation.code_generated' "
            "ORDER BY created_at DESC LIMIT 1"
        )
    ).all()
    assert len(rows) == 1
    assert str(rows[0].actor_id) == str(admin.id)
    assert str(rows[0].entity_id) == str(target.id)


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


def test_generate_raises_when_target_soldier_missing(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-10", role="admin")

    try:
        generate_activation_code(admin_session, target_soldier_id=uuid.uuid4(), actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "soldier_not_found"


def test_commander_cannot_generate_for_target_with_no_hierarchy_node(admin_session):
    node = create_node(admin_session, level="group", name="hract_mador_c")
    commander = create_soldier(admin_session, personal_number="hract-cmd-4", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-15", hierarchy_node_id=None)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is False


def test_commander_cannot_generate_for_target_with_dangling_hierarchy_node(admin_session):
    node = create_node(admin_session, level="group", name="hract_mador_d")
    commander = create_soldier(admin_session, personal_number="hract-cmd-5", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-16", hierarchy_node_id=node.id)
    admin_session.commit()
    # Point the target at a hierarchy node id that does not exist. The
    # mutation is never flushed/committed to the DB (it would violate the FK
    # constraint) — no_autoflush keeps the in-memory value visible to the
    # lookup inside can_generate_activation_code without triggering a flush.
    target.hierarchy_node_id = uuid.uuid4()
    with admin_session.no_autoflush:
        result = can_generate_activation_code(admin_session, actor=commander, target=target)

    assert result is False


def test_min_commander_level_setting_overrides_default(admin_session):
    node = create_node(admin_session, level="team", name="hract_team_setting")
    commander = create_soldier(admin_session, personal_number="hract-cmd-6", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-17", hierarchy_node_id=node.id)
    set_setting(admin_session, "hr_activation.min_commander_level", "team", actor_id=None)
    admin_session.commit()

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is True
