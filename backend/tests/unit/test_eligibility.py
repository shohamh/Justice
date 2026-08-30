from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import (
    DutyType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    Soldier,
    SoldierRangeQualification,
)
from app.services.eligibility import (
    DutyTypeRequirements,
    _is_eligible,
    compute_eligibility_exclusions,
    duty_type_ineligibility_reason,
    inferred_service_type,
)
from app.services.range_coverage import get_range_coverage, get_range_coverages
from app.services.weapon_eligibility import compute_eligibility
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_range_event, create_range_location, create_soldier


def _soldier(**kwargs) -> Soldier:
    defaults = dict(
        personal_number="test",
        full_name="Test",
        password_hash="x",
        role="soldier",
        enrolled_at=date(2024, 1, 1),
        bahad1_graduate=False,
        has_military_driving_license=False,
    )
    defaults.update(kwargs)
    return Soldier(**defaults)


TODAY = date(2026, 6, 1)


def test_service_type_hobah():
    s = _soldier(mandatory_end_date=date(2027, 1, 1))
    assert inferred_service_type(s, TODAY) == "חובה"


def test_service_type_keva():
    s = _soldier(mandatory_end_date=date(2025, 1, 1), discharge_date=None)
    assert inferred_service_type(s, TODAY) == "קבע"


def test_service_type_unknown():
    s = _soldier()
    assert inferred_service_type(s, TODAY) is None


def test_no_requirements_passes():
    s = _soldier()
    reqs = DutyTypeRequirements()
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_gender_restriction_passes():
    s = _soldier(gender="male")
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_gender_restriction_blocks():
    s = _soldier(gender="female")
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_gender_blocked_if_restriction():
    s = _soldier(gender=None)
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_duty_type_ineligibility_reason_none_when_eligible():
    s = _soldier(gender="male")
    dt = DutyType(name="dt_reason_ok", score_per_day=Decimal("1.00"), requirements={"allowed_genders": ["male"]})
    assert duty_type_ineligibility_reason(s, dt, mitvahim_months=6, alal_months=3, today=TODAY) is None


def test_duty_type_ineligibility_reason_none_when_no_requirements():
    s = _soldier(gender="female")
    dt = DutyType(name="dt_reason_none", score_per_day=Decimal("1.00"), requirements={})
    assert duty_type_ineligibility_reason(s, dt, mitvahim_months=6, alal_months=3, today=TODAY) is None


def test_duty_type_ineligibility_reason_describes_gender_mismatch():
    s = _soldier(gender="female")
    dt = DutyType(name="dt_reason_gender", score_per_day=Decimal("1.00"), requirements={"allowed_genders": ["male"]})
    reason = duty_type_ineligibility_reason(s, dt, mitvahim_months=6, alal_months=3, today=TODAY)
    assert reason == "מגדר לא מתאים לדרישות התורנות"


def test_duty_type_ineligibility_reason_describes_stale_mitvahim():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=400))
    dt = DutyType(name="dt_reason_mitvahim", score_per_day=Decimal("1.00"), requirements={"requires_mitvahim": True})
    reason = duty_type_ineligibility_reason(s, dt, mitvahim_months=6, alal_months=3, today=TODAY)
    assert reason == "לא בוצע מטווח מבצעי בטווח הזמן הנדרש"


def test_mitvahim_fresh_passes():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=30))
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_mitvahim_stale_blocks():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=200))
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_mitvahim_blocks():
    s = _soldier(last_mitvahim_date=None)
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_rank_restriction_passes():
    s = _soldier(rank="סמל")
    reqs = DutyTypeRequirements(allowed_ranks=["סמל", "סמר"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_rank_restriction_blocks():
    s = _soldier(rank="טוראי")
    reqs = DutyTypeRequirements(allowed_ranks=["סמל", "סמר"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_rank_blocked_if_restriction():
    s = _soldier(rank=None)
    reqs = DutyTypeRequirements(allowed_ranks=["סמל"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_is_eligible_uses_rank_override_when_provided():
    s = _soldier(rank="טוראי")
    reqs = DutyTypeRequirements(allowed_ranks=["רבט"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY) is False
    assert _is_eligible(
        s, reqs, mitvahim_months=6, alal_months=3, today=TODAY, rank_override="רבט"
    ) is True


def test_officers_not_allowed():
    s = _soldier(is_officer=True)
    reqs = DutyTypeRequirements(officers_allowed=False)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_enlisted_not_allowed():
    s = _soldier(is_officer=False)
    reqs = DutyTypeRequirements(enlisted_allowed=False)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_bahad1_required_passes():
    s = _soldier(bahad1_graduate=True)
    reqs = DutyTypeRequirements(requires_bahad1=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_bahad1_required_blocks():
    s = _soldier(bahad1_graduate=False)
    reqs = DutyTypeRequirements(requires_bahad1=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_service_type_restriction_blocks():
    s = _soldier(mandatory_end_date=date(2025, 1, 1), discharge_date=None)
    # soldier is קבע, but restriction only allows חובה
    reqs = DutyTypeRequirements(allowed_service_types=["חובה"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_required_passes_no_expiry():
    s = _soldier(has_military_driving_license=True, military_driving_license_expiry=None)
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_required_blocks_when_absent():
    s = _soldier(has_military_driving_license=False)
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_required_blocks_when_null():
    s = _soldier(has_military_driving_license=None)
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_future_expiry_passes():
    s = _soldier(has_military_driving_license=True, military_driving_license_expiry=TODAY + timedelta(days=30))
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_past_expiry_blocks():
    s = _soldier(has_military_driving_license=True, military_driving_license_expiry=TODAY - timedelta(days=1))
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_compute_eligibility_exclusions_respects_reference_date(admin_session):
    """A soldier whose mitvahim (shooting range qualification) will have
    expired by a FUTURE reference date, but hasn't expired yet as of today,
    must be excluded when evaluated as-of that future date — not as-of
    today's date."""
    dt = DutyType(
        name=f"ref_date_dt_{uuid.uuid4().hex[:8]}", score_per_day=1,
        requirements={"requires_mitvahim": True},
    )
    admin_session.add(dt)
    admin_session.flush()

    soldier = create_soldier(admin_session, personal_number=f"ref_date_s_{uuid.uuid4().hex[:8]}")
    soldier.last_mitvahim_date = date.today() - timedelta(days=170)  # ~5.5 months ago
    admin_session.commit()

    # As of today (6-month default window), still eligible.
    today_exclusions = compute_eligibility_exclusions(
        admin_session, [soldier], mitvahim_months=6, alal_months=3, reference_date=date.today(),
    )
    assert dt.id not in today_exclusions.get(soldier.id, set())

    # As of 60 days in the future, the mitvahim will be ~7.8 months stale — excluded.
    future_exclusions = compute_eligibility_exclusions(
        admin_session, [soldier], mitvahim_months=6, alal_months=3, reference_date=date.today() + timedelta(days=60),
    )
    assert dt.id in future_exclusions.get(soldier.id, set())


def test_range_eligibility_is_date_aware_for_primary_assignment(admin_session):
    node = create_node(admin_session, level="branch", name="eligibility sequencing")
    soldier = create_soldier(admin_session, personal_number="eligibility-sequencing", hierarchy_node_id=node.id)
    earlier = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2), range_location=create_range_location(admin_session),
    )
    later = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=12), range_location=create_range_location(admin_session),
    )
    admin_session.add(RangeAssignment(range_event_id=earlier.id, soldier_id=soldier.id, is_reserve=False))
    admin_session.commit()
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)

    assert compute_eligibility(
        admin_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )[0] is True
    assert compute_eligibility(
        admin_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=1),
    )[0] is False


def test_range_eligibility_does_not_count_pending_or_draft_reserve_assignment(admin_session):
    node = create_node(admin_session, level="branch", name="eligibility reserve sequencing")
    soldier = create_soldier(admin_session, personal_number="eligibility-reserve", hierarchy_node_id=node.id)
    reserve_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2), range_location=create_range_location(admin_session),
    )
    draft_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=3), range_location=create_range_location(admin_session),
    )
    draft_reserve_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=4), range_location=create_range_location(admin_session),
    )
    admin_session.add_all([
        RangeAssignment(range_event_id=reserve_event.id, soldier_id=soldier.id, is_reserve=True, attendance_status="pending"),
        RangeAssignment(range_event_id=draft_event.id, soldier_id=soldier.id, is_reserve=False, is_draft=True),
        RangeAssignment(range_event_id=draft_reserve_event.id, soldier_id=soldier.id, is_reserve=True, is_draft=True, attendance_status="present"),
    ])
    admin_session.commit()
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)

    eligible, reason = compute_eligibility(
        admin_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=date.today() + timedelta(days=5),
    )

    assert eligible is False
    assert reason == "weapon_qualification"


def test_confirmed_reserve_range_provides_reserve_like_coverage(admin_session):
    node = create_node(admin_session, level="branch", name="eligibility confirmed reserve")
    soldier = create_soldier(admin_session, personal_number="eligibility-confirmed-reserve", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2), range_location=create_range_location(admin_session),
    )
    admin_session.add(RangeAssignment(
        range_event_id=event.id, soldier_id=soldier.id, is_reserve=True, attendance_status="present",
    ))
    admin_session.commit()
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)

    eligible, reason = compute_eligibility(
        admin_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=3),
    )

    assert eligible is True
    assert reason is None


@pytest.mark.parametrize(
    ("assignment_kwargs", "has_pending_excusal", "expected_eligible"),
    [
        ({}, False, True),
        ({"is_reserve": True, "attendance_status": RangeAttendanceStatus.present}, False, True),
        ({"is_reserve": True, "attendance_status": RangeAttendanceStatus.pending}, False, False),
        ({}, True, False),
        ({"is_draft": True}, False, False),
    ],
    ids=["primary", "completed-reserve", "unconfirmed-reserve", "pending-primary", "draft-primary"],
)
def test_range_eligibility_projects_only_guaranteed_future_range_coverage_at_duty_date(
    admin_session, assignment_kwargs, has_pending_excusal, expected_eligible,
):
    """A mutation that treats any future assignment as qualification must fail here."""
    node = create_node(admin_session, level="branch", name="future eligibility coverage")
    soldier = create_soldier(
        admin_session, personal_number=f"future-eligibility-{uuid.uuid4().hex[:8]}", hierarchy_node_id=node.id,
    )
    range_date = date.today() + timedelta(days=2)
    event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.live,
        event_date=range_date, range_location=create_range_location(admin_session),
    )
    assignment = RangeAssignment(
        range_event_id=event.id,
        soldier_id=soldier.id,
        **{"is_reserve": False, **assignment_kwargs},
    )
    admin_session.add(assignment)
    admin_session.flush()
    if has_pending_excusal:
        admin_session.add(RangeExcusalRequest(
            range_assignment_id=assignment.id,
            range_event_id=event.id,
            requested_by=None,
            reason="pending",
            status=RangeExcusalStatus.pending,
        ))
    admin_session.commit()
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)

    eligible, reason = compute_eligibility(
        admin_session,
        soldier_id=soldier.id,
        required_range_type=RangeType.laser,
        as_of=range_date + timedelta(days=1),
    )

    assert eligible is expected_eligible
    assert reason == (None if expected_eligible else "weapon_qualification")


def test_range_coverage_classifies_qualification_primary_reserve_and_later_range(admin_session):
    node = create_node(admin_session, level="branch", name="shared coverage")
    as_of = date.today() + timedelta(days=10)
    qualified = create_soldier(admin_session, personal_number="coverage-qualified", hierarchy_node_id=node.id)
    primary = create_soldier(admin_session, personal_number="coverage-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(admin_session, personal_number="coverage-reserve", hierarchy_node_id=node.id)
    later = create_soldier(admin_session, personal_number="coverage-later", hierarchy_node_id=node.id)
    pending = create_soldier(admin_session, personal_number="coverage-pending", hierarchy_node_id=node.id)
    draft = create_soldier(admin_session, personal_number="coverage-draft", hierarchy_node_id=node.id)
    admin_session.add(SoldierRangeQualification(
        soldier_id=qualified.id, range_type=RangeType.live, valid_until=as_of,
    ))
    earlier_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=as_of - timedelta(days=2), range_location=create_range_location(admin_session),
    )
    later_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=as_of + timedelta(days=1), range_location=create_range_location(admin_session),
    )
    pending_assignment = RangeAssignment(
        range_event_id=earlier_event.id, soldier_id=pending.id, is_reserve=False,
    )
    admin_session.add_all([
        RangeAssignment(range_event_id=earlier_event.id, soldier_id=primary.id, is_reserve=False),
        RangeAssignment(
            range_event_id=earlier_event.id, soldier_id=reserve.id, is_reserve=True, attendance_status="present",
        ),
        RangeAssignment(range_event_id=later_event.id, soldier_id=later.id, is_reserve=False),
        pending_assignment,
        RangeAssignment(range_event_id=earlier_event.id, soldier_id=draft.id, is_reserve=False, is_draft=True),
    ])
    admin_session.flush()
    admin_session.add(RangeExcusalRequest(
        range_assignment_id=pending_assignment.id,
        range_event_id=earlier_event.id,
        requested_by=None,
        reason="pending",
        status=RangeExcusalStatus.pending,
    ))
    admin_session.commit()

    coverages = get_range_coverages(
        admin_session,
        soldier_ids=[qualified.id, primary.id, reserve.id, later.id, pending.id, draft.id],
        required_range_type=RangeType.laser,
        as_of=as_of,
    )

    assert coverages[qualified.id].coverage_kind == "qualification"
    assert coverages[qualified.id].valid_until == as_of
    assert coverages[primary.id].coverage_kind == "primary_range"
    assert coverages[primary.id].qualified is True
    assert coverages[primary.id].source_event_date == earlier_event.date
    assert coverages[reserve.id].coverage_kind == "reserve_range"
    assert coverages[reserve.id].qualified is True
    assert get_range_coverage(
        admin_session, soldier_id=later.id, required_range_type=RangeType.laser, as_of=as_of,
    ).coverage_kind == "none"
    assert coverages[pending.id].coverage_kind == "none"
    assert coverages[draft.id].coverage_kind == "none"


def test_range_coverage_prefers_strongest_source_over_earliest(admin_session):
    """Source KIND decides, date only breaks ties inside a kind. The two
    qualification-holding soldiers report ``qualification`` even though their range
    assignments are earlier; the two soldiers without one keep reporting the exact
    source date and validity window of their single range source."""
    node = create_node(admin_session, level="branch", name="coverage source ordering")
    as_of = date.today() + timedelta(days=20)
    primary = create_soldier(admin_session, personal_number="coverage-earliest-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(admin_session, personal_number="coverage-earliest-reserve", hierarchy_node_id=node.id)
    primary_only = create_soldier(admin_session, personal_number="coverage-primary-only", hierarchy_node_id=node.id)
    reserve_only = create_soldier(admin_session, personal_number="coverage-reserve-only", hierarchy_node_id=node.id)
    reserve_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=as_of - timedelta(days=6), range_location=create_range_location(admin_session),
    )
    primary_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=as_of - timedelta(days=5), range_location=create_range_location(admin_session),
    )
    qualification_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.live,
        event_date=as_of - timedelta(days=2), range_location=create_range_location(admin_session),
    )
    admin_session.add_all([
        RangeAssignment(range_event_id=primary_event.id, soldier_id=primary.id, is_reserve=False),
        RangeAssignment(
            range_event_id=reserve_event.id, soldier_id=reserve.id, is_reserve=True, attendance_status="present",
        ),
        RangeAssignment(range_event_id=primary_event.id, soldier_id=primary_only.id, is_reserve=False),
        RangeAssignment(
            range_event_id=reserve_event.id, soldier_id=reserve_only.id, is_reserve=True,
            attendance_status="present",
        ),
        SoldierRangeQualification(
            soldier_id=primary.id,
            range_type=RangeType.live,
            valid_until=as_of + timedelta(days=40),
            source_range_event_id=qualification_event.id,
        ),
        SoldierRangeQualification(
            soldier_id=reserve.id,
            range_type=RangeType.live,
            valid_until=as_of + timedelta(days=40),
            source_range_event_id=qualification_event.id,
        ),
    ])
    admin_session.commit()
    set_setting(admin_session, "mitvachim.laser_validity_days", 30, actor_id=None)

    coverages = get_range_coverages(
        admin_session,
        soldier_ids=[primary.id, reserve.id, primary_only.id, reserve_only.id],
        required_range_type=RangeType.laser,
        as_of=as_of,
    )

    # Qualification is the strongest kind, so it wins over both range sources even
    # though those sit earlier. A qualification sourced from a range event uses the
    # current validity setting for that source range type.
    assert coverages[primary.id].coverage_kind == "qualification"
    assert coverages[primary.id].valid_until == qualification_event.date + timedelta(days=365)
    assert coverages[reserve.id].coverage_kind == "qualification"
    assert coverages[reserve.id].valid_until == qualification_event.date + timedelta(days=365)

    assert coverages[primary_only.id].coverage_kind == "primary_range"
    assert coverages[primary_only.id].source_event_date == primary_event.date
    assert coverages[primary_only.id].valid_until == primary_event.date + timedelta(days=30)
    assert coverages[reserve_only.id].coverage_kind == "reserve_range"
    assert coverages[reserve_only.id].source_event_date == reserve_event.date
    assert coverages[reserve_only.id].valid_until == reserve_event.date + timedelta(days=30)


def test_range_coverage_prefers_later_primary_over_earlier_reserve(admin_session):
    """The exact regression: an earlier confirmed reserve range must not mask a later
    planned primary range, which would drop the soldier out of the qualified tier."""
    node = create_node(admin_session, level="branch", name="coverage strength over date")
    as_of = date.today() + timedelta(days=20)
    soldier = create_soldier(
        admin_session, personal_number="coverage-strength-mixed", hierarchy_node_id=node.id,
    )
    reserve_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=as_of - timedelta(days=6), range_location=create_range_location(admin_session),
    )
    primary_event = create_range_event(
        admin_session, hierarchy_node=node, range_type=RangeType.laser,
        event_date=as_of - timedelta(days=2), range_location=create_range_location(admin_session),
    )
    admin_session.add_all([
        RangeAssignment(
            range_event_id=reserve_event.id, soldier_id=soldier.id, is_reserve=True,
            attendance_status="present",
        ),
        RangeAssignment(range_event_id=primary_event.id, soldier_id=soldier.id, is_reserve=False),
    ])
    admin_session.commit()
    set_setting(admin_session, "mitvachim.laser_validity_days", 30, actor_id=None)

    coverage = get_range_coverage(
        admin_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=as_of,
    )

    assert coverage.coverage_kind == "primary_range"
    assert coverage.source_event_date == primary_event.date
    assert coverage.valid_until == primary_event.date + timedelta(days=30)
