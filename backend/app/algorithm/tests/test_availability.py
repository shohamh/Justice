from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.availability import analyze_duty_availability, eligibility_blockers
from app.algorithm.diagnose import diagnose_infeasibility
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput


def test_eligibility_blockers_report_range_and_military_license_requirements():
    duty = DutyBlock(
        id=uuid4(),
        duty_type_id=uuid4(),
        duty_location_id=uuid4(),
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 16),
        score_per_day=Decimal("1"),
        required_range_type="laser",
        requirements={"requires_military_driving_license": True},
    )
    soldier = SoldierInput(
        id=uuid4(),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=100,
        weapon_ineligible_duty_block_ids={duty.id},
        future_ineligible_duty_block_ids={duty.id},
    )

    assert eligibility_blockers(soldier, duty) == {
        "range_qualification",
        "military_driving_license",
    }


def test_availability_counts_qualified_and_currently_free_soldiers():
    duty = DutyBlock(
        id=uuid4(),
        duty_type_id=uuid4(),
        duty_location_id=uuid4(),
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 16),
        score_per_day=Decimal("1"),
    )
    qualified = SoldierInput(
        id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100
    )
    unqualified = SoldierInput(
        id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100,
        future_ineligible_duty_block_ids={duty.id},
    )
    existing = [ExistingAssignment(
        soldier_id=qualified.id,
        duty_type_id=uuid4(),
        start_date=duty.start_date,
        end_date=duty.end_date,
    )]

    result = analyze_duty_availability(
        [qualified, unqualified], duty, existing=existing,
    )

    assert result.eligible_count == 1
    assert result.available_count == 0
    assert result.blocker_counts == {"duty_requirements": 1, "schedule_conflict": 1}


def test_diagnosis_names_hard_requirement_shortages():
    duty = DutyBlock(
        id=uuid4(),
        duty_type_id=uuid4(),
        duty_location_id=uuid4(),
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 16),
        score_per_day=Decimal("1"),
        required_range_type="laser",
        requirements={"requires_military_driving_license": True},
    )
    soldier = SoldierInput(
        id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100,
        weapon_ineligible_duty_block_ids={duty.id},
        future_ineligible_duty_block_ids={duty.id},
    )

    reasons = diagnose_infeasibility(
        [soldier], [duty], [], {duty.duty_type_id: "נהג תורן"},
    )

    assert any("מטווח" in reason for reason in reasons)
    assert any("רשנ" in reason for reason in reasons)
