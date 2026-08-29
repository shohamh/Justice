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

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 10, 1), range_type="laser") is True


def test_time_limited_forbids_weapons_exemption_covering_event_date_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")
    soldier = create_soldier(app_session, personal_number="2000002", hierarchy_node_id=node.id)
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is True


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

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False


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

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False


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

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is True


def test_eligible_for_a_weapon_duty_type_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ז")
    soldier = create_soldier(app_session, personal_number="2000006", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק 2", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False


def test_no_weapon_duty_types_exist_at_all_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ח")
    soldier = create_soldier(app_session, personal_number="2000007", hierarchy_node_id=node.id)

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is True


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

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False


def test_eligible_when_duty_type_has_unrestricted_eligible_node_ids(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה כלל ארצי")
    soldier = create_soldier(app_session, personal_number="2000010", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק כלל ארצי", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=None,
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False


def test_plain_exemption_plus_structural_ineligibility_still_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה תת-בדיקה")
    soldier = create_soldier(app_session, personal_number="2000008", hierarchy_node_id=node.id)
    _grant_exemption(app_session, soldier.id, is_global=False, forbids_weapons=False, end_date=None)
    # No requires_weapon=True duty type is eligible for this node -> structurally exempt,
    # and the presence of the unrelated plain exemption above must not change that.

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is True


def test_soldier_needing_only_laser_is_exempt_from_alal_event(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה לייזר בלבד")
    soldier = create_soldier(app_session, personal_number="2000011", hierarchy_node_id=node.id)
    laser_duty = DutyType(
        name="שמירה לייזר בלבד", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type="laser", eligible_node_ids=[node.id],
    )
    app_session.add(laser_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False
    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="alal") is True


def test_soldier_needing_alal_is_not_exempt_from_alal_event(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה הגנש")
    soldier = create_soldier(app_session, personal_number="2000012", hierarchy_node_id=node.id)
    alal_duty = DutyType(
        name='הגנ"ש בדיקה', score_per_day=Decimal("1.00"),
        requires_weapon=False, required_range_type="alal", eligible_node_ids=[node.id],
    )
    app_session.add(alal_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="alal") is False


def test_generic_untiered_weapon_duty_is_relevant_to_laser_and_live_but_not_alal(app_session: Session) -> None:
    """Most duty types in this codebase (e.g. escort duty) never set a tier at
    all and have always counted as basic weapon-range eligibility, so the
    generic fallback must keep covering laser/live. Alal is the one tier with
    its own dedicated relevance rule (`alal_relevance.py`), which never treats
    an untiered duty as alal-relevant — this must match that exactly, or a
    soldier who never structurally needs alal would still show up as an alal
    candidate through this fallback alone."""
    node = create_node(app_session, level="פלוגה", name="פלוגה כללי")
    soldier = create_soldier(app_session, personal_number="2000013", hierarchy_node_id=node.id)
    generic_duty = DutyType(
        name="ליווים בדיקה", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=None, eligible_node_ids=[node.id],
    )
    app_session.add(generic_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="laser") is False
    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="live") is False
    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1), range_type="alal") is True
