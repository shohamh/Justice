"""The ineligible-soldier count must always equal the length of the list.

``count_ineligible_soldiers`` is a fast path for the shell badge; it must never
drift from ``list_ineligible_soldiers``. This builds one small hierarchy that
covers every branch of the selection and compares both for admin (roots=None)
and for scoped root sets.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import DutyAssignment, DutyType, RangeType, SoldierRangeQualification
from app.services import ineligible_soldiers as svc
from app.services.settings_loader import set_setting
from tests.helpers import create_duty_location, create_node, create_soldier

pytestmark = pytest.mark.misc


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _soldier(session, node, *, gender: str | None = "male", **fields):
    soldier = create_soldier(
        session, personal_number=f"parity-{_uid()}", hierarchy_node_id=node.id if node else None
    )
    soldier.gender = gender
    for name, value in fields.items():
        setattr(soldier, name, value)
    return soldier


def _qualify(session, soldier, *, days: int) -> None:
    session.add(
        SoldierRangeQualification(
            soldier_id=soldier.id,
            range_type=RangeType.laser,
            valid_until=date.today() + timedelta(days=days),
        )
    )


def _duty(session, soldier, duty_type, location, *, in_days: int) -> None:
    session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date.today() + timedelta(days=in_days),
            end_date=date.today() + timedelta(days=in_days),
            status="published",
        )
    )


@pytest.fixture()
def seeded(admin_session):
    session = admin_session
    set_setting(session, "mitvachim.enabled", True, actor_id=None)
    division = create_node(session, level="division", name=f"parity-div-{_uid()}")
    team = create_node(session, level="team", name=f"parity-team-{_uid()}", parent=division)
    other = create_node(session, level="division", name=f"parity-other-{_uid()}")
    location = create_duty_location(session, name=f"parity-location-{_uid()}")
    # Only male soldiers are structurally eligible for the single weapon duty type.
    weapon_duty = DutyType(
        name=f"parity-weapon-{_uid()}",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        required_range_type=RangeType.laser,
        requirements={"allowed_genders": ["male"], "requires_mitvahim": True},
    )
    inactive_duty = DutyType(
        name=f"parity-inactive-{_uid()}",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        active=False,
    )
    # Females with a military driving licence qualify only for this one, so a
    # soldier's structural verdict depends on more than one profile field.
    licensed_duty = DutyType(
        name=f"parity-licensed-{_uid()}",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        requirements={
            "allowed_genders": ["female"],
            "requires_military_driving_license": True,
        },
    )
    session.add_all([weapon_duty, inactive_duty, licensed_duty])
    session.flush()

    no_qualification = _soldier(session, team)
    expires_before_duty = _soldier(session, team)
    _qualify(session, expires_before_duty, days=1)
    _duty(session, expires_before_duty, weapon_duty, location, in_days=7)
    fully_eligible = _soldier(session, team)
    _qualify(session, fully_eligible, days=30)
    _duty(session, fully_eligible, weapon_duty, location, in_days=7)
    qualified_no_duty = _soldier(session, division)
    _qualify(session, qualified_no_duty, days=30)
    profile_qualified = _soldier(
        session, division, last_mitvahim_date=date.today() - timedelta(days=10)
    )
    structurally_ineligible = _soldier(session, team, gender="female")
    licensed_female = _soldier(
        session,
        team,
        gender="female",
        has_military_driving_license=True,
        military_driving_license_expiry=date.today() + timedelta(days=60),
    )
    expired_license_female = _soldier(
        session,
        team,
        gender="female",
        has_military_driving_license=True,
        military_driving_license_expiry=date.today() - timedelta(days=1),
    )
    unknown_gender = _soldier(session, division, gender=None)
    left_unit = _soldier(session, team, left_at=date.today() - timedelta(days=5))
    outside_scope = _soldier(session, other)
    no_node = _soldier(session, None)
    session.commit()
    return {
        "division": division,
        "team": team,
        "other": other,
        "no_qualification": no_qualification,
        "expires_before_duty": expires_before_duty,
        "fully_eligible": fully_eligible,
        "qualified_no_duty": qualified_no_duty,
        "profile_qualified": profile_qualified,
        "structurally_ineligible": structurally_ineligible,
        "licensed_female": licensed_female,
        "expired_license_female": expired_license_female,
        "unknown_gender": unknown_gender,
        "left_unit": left_unit,
        "outside_scope": outside_scope,
        "no_node": no_node,
    }


def _assert_parity(session, roots, expected_ids) -> None:
    as_of = date.today()
    listed = svc.list_ineligible_soldiers(session, roots=roots, as_of=as_of)
    assert {record.soldier_id for record in listed} == expected_ids
    assert svc.count_ineligible_soldiers(session, roots=roots, as_of=as_of) == len(listed)


def test_count_matches_list_for_admin_scope(admin_session, seeded) -> None:
    _assert_parity(
        admin_session,
        None,
        {
            seeded["no_qualification"].id,
            seeded["expires_before_duty"].id,
            seeded["left_unit"].id,
            seeded["licensed_female"].id,
            seeded["outside_scope"].id,
        },
    )


def test_count_matches_list_for_team_scope(admin_session, seeded) -> None:
    _assert_parity(
        admin_session,
        {seeded["team"].id},
        {
            seeded["no_qualification"].id,
            seeded["expires_before_duty"].id,
            seeded["left_unit"].id,
            seeded["licensed_female"].id,
        },
    )


def test_count_matches_list_for_overlapping_multi_root_scope(admin_session, seeded) -> None:
    _assert_parity(
        admin_session,
        {seeded["division"].id, seeded["team"].id},
        {
            seeded["no_qualification"].id,
            seeded["expires_before_duty"].id,
            seeded["left_unit"].id,
            seeded["licensed_female"].id,
        },
    )


def test_count_matches_list_for_empty_scope(admin_session, seeded) -> None:
    _assert_parity(admin_session, set(), set())


def test_count_row_profile_matches_named_structural_fields(admin_session, seeded) -> None:
    rows = admin_session.execute(select(*svc._COUNT_SOLDIER_COLUMNS)).all()
    assert rows
    for row in rows:
        assert svc._count_row_profile(row) == svc._structural_profile(row)


class _RecordingSoldier:
    """Answers every attribute with a value that passes, recording the name."""

    _values = {
        "gender": "male",
        "rank": "סרן",
        "mandatory_end_date": date.today() + timedelta(days=30),
        "last_mitvahim_date": date.today(),
        "last_alal_date": date.today(),
        "is_officer": True,
        "bahad1_graduate": True,
        "has_military_driving_license": True,
        "military_driving_license_expiry": date.today() + timedelta(days=30),
    }

    def __init__(self, *, is_officer: bool) -> None:
        self.read: set[str] = set()
        self._is_officer = is_officer

    def __getattr__(self, name: str):
        self.read.add(name)
        if name == "is_officer":
            return self._is_officer
        return self._values.get(name)


def test_structural_grouping_covers_every_field_is_eligible_reads() -> None:
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    strict = {
        "allowed_genders": ["male"],
        "requires_mitvahim": True,
        "requires_alal": True,
        "allowed_ranks": ["סרן"],
        "allowed_service_types": ["חובה"],
        "requires_bahad1": True,
        "requires_military_driving_license": True,
    }
    read: set[str] = set()
    for is_officer, extra in (
        (False, {"officers_allowed": False}),
        (True, {"enlisted_allowed": False}),
        (True, {"rank_service_types": {"סרן": ["חובה"]}}),
    ):
        soldier = _RecordingSoldier(is_officer=is_officer)
        requirements = DutyTypeRequirements.model_validate({**strict, **extra})
        assert _is_eligible(
            soldier, requirements, mitvahim_months=6, alal_months=3, today=date.today()
        )
        read |= soldier.read
    assert read == set(svc._STRUCTURAL_ELIGIBILITY_FIELDS)


def test_count_matches_list_when_enforcement_disabled(admin_session, seeded) -> None:
    set_setting(admin_session, "mitvachim.enabled", False, actor_id=None)
    admin_session.commit()
    _assert_parity(
        admin_session,
        None,
        {
            seeded["no_qualification"].id,
            seeded["left_unit"].id,
            seeded["licensed_female"].id,
            seeded["outside_scope"].id,
        },
    )
