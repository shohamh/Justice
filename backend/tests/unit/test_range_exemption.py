from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyType, ExemptionType, SoldierExemption
from app.services.range_exemption import is_range_exempt
from tests.helpers import create_node, create_soldier


def _grant_exemption(session: Session, soldier_id, *, is_global=False, forbids_weapons=False,
                      start_date=None, end_date=None) -> SoldierExemption:
    et = ExemptionType(name=f"type-{soldier_id}-{is_global}-{forbids_weapons}",
                        is_global=is_global, forbids_weapons=forbids_weapons)
    session.add(et)
    session.flush()
    se = SoldierExemption(
        soldier_id=soldier_id, exemption_type_id=et.id,
        start_date=start_date or date(2020, 1, 1), end_date=end_date,
    )
    session.add(se)
    session.flush()
    return se


def test_global_exemption_covering_event_date_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")
    soldier = create_soldier(app_session, personal_number="2000001", hierarchy_node_id=node.id)
    _grant_exemption(app_session, soldier.id, is_global=True, end_date=None)

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 10, 1)) is True


def test_time_limited_forbids_weapons_exemption_covering_event_date_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")
    soldier = create_soldier(app_session, personal_number="2000002", hierarchy_node_id=node.id)
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True


def test_expired_forbids_weapons_exemption_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ג")
    soldier = create_soldier(app_session, personal_number="2000003", hierarchy_node_id=node.id)
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
    )
    # Make the soldier structurally eligible for a weapon duty type so the only
    # thing under test is whether the expired exemption still exempts (it must not).
    weapon_duty = DutyType(
        name="שמירה עם נשק 3", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_plain_exemption_not_global_not_forbids_weapons_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ד")
    soldier = create_soldier(app_session, personal_number="2000004", hierarchy_node_id=node.id)
    _grant_exemption(app_session, soldier.id, is_global=False, forbids_weapons=False, end_date=None)
    # Make the soldier structurally eligible for a weapon duty type so the only
    # thing under test is whether the irrelevant exemption itself exempts (it must not).
    weapon_duty = DutyType(
        name="שמירה עם נשק 4", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_structurally_ineligible_for_any_weapon_duty_type_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ה")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ו")
    soldier = create_soldier(app_session, personal_number="2000005", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[other_node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True


def test_eligible_for_a_weapon_duty_type_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ז")
    soldier = create_soldier(app_session, personal_number="2000006", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק 2", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_no_weapon_duty_types_exist_at_all_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ח")
    soldier = create_soldier(app_session, personal_number="2000007", hierarchy_node_id=node.id)

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True


def test_eligible_via_descendant_node_of_duty_types_eligible_node(app_session: Session) -> None:
    parent = create_node(app_session, level="פלוגה", name="פלוגה הורה")
    child = create_node(app_session, level="פלוגה", name="פלוגה צאצא", parent=parent)
    soldier = create_soldier(app_session, personal_number="2000009", hierarchy_node_id=child.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק הורה", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[parent.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_eligible_when_duty_type_has_unrestricted_eligible_node_ids(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה כלל ארצי")
    soldier = create_soldier(app_session, personal_number="2000010", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק כלל ארצי", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=None,
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_plain_exemption_plus_structural_ineligibility_still_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה תת-בדיקה")
    soldier = create_soldier(app_session, personal_number="2000008", hierarchy_node_id=node.id)
    _grant_exemption(app_session, soldier.id, is_global=False, forbids_weapons=False, end_date=None)
    # No requires_weapon=True duty type is eligible for this node -> structurally exempt,
    # and the presence of the unrelated plain exemption above must not change that.

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True
