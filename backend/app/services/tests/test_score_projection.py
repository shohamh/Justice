from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionType,
    SoldierExemption,
)
from app.services.adjustments import create_adjustment
from app.services.duty_config import map_exemption_to_duty_type
from app.services.effort_score import compute_effort_breakdown, quarter_end
from app.services.scoring import active_days, cumulative_score, effective_duty_spans
from app.services.score_projection import project_all_buckets, project_soldier_bucket
from app.services.settings_loader import set_setting
from tests.helpers import create_soldier


def _duty_type(session, *, name: str, score: str = "1.00") -> DutyType:
    duty_type = DutyType(name=name, score_per_day=Decimal(score))
    session.add(duty_type)
    session.flush()
    return duty_type


def _location(session, *, name: str) -> DutyLocation:
    location = DutyLocation(name=name)
    session.add(location)
    session.flush()
    return location


def _grant_full_coverage_exemption(session, *, soldier_id, start_date: date, end_date: date) -> None:
    exemption_type = ExemptionType(name=f"full-coverage-{soldier_id}")
    session.add(exemption_type)
    session.flush()
    active_duty_type_ids = (
        session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )
    for duty_type_id in active_duty_type_ids:
        map_exemption_to_duty_type(
            session, exemption_type_id=exemption_type.id, duty_type_id=duty_type_id, actor_id=None
        )
    session.add(
        SoldierExemption(
            soldier_id=soldier_id,
            exemption_type_id=exemption_type.id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    session.flush()


def _quarter_shift_count(session, *, soldier_id, quarter_start_value: date) -> int:
    spans = effective_duty_spans(
        session,
        soldier_ids={soldier_id},
        date_from=quarter_start_value,
        date_to=quarter_end(quarter_start_value),
    )
    return len(
        {
            span["assignment_id"]
            for span in spans
            if span["start_date"] <= quarter_end(quarter_start_value)
            and span["end_date"] > quarter_start_value
        }
    )


def _canonical_bucket_summary(
    session,
    *,
    soldier,
    quarter_start_value: date,
    planning_start: date,
    reset_date: date,
) -> tuple[Decimal, Decimal, int]:
    breakdown = compute_effort_breakdown(
        session,
        soldier=soldier,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )
    quarter_detail = next(
        detail for detail in breakdown.quarters if detail.quarter_start == quarter_start_value
    )
    adjustment_score = quarter_detail.adjustment_delta
    duty_score = quarter_detail.soldier_score - adjustment_score
    shift_count = _quarter_shift_count(
        session, soldier_id=soldier.id, quarter_start_value=quarter_start_value
    )
    return duty_score, adjustment_score, shift_count


def _seed_projection_scenario(admin_session):
    set_setting(
        admin_session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None
    )
    set_setting(
        admin_session, "scoring.reserve_called_up_multiplier", Decimal("1.3"), actor_id=None
    )
    set_setting(admin_session, "scoring.dismissed_multiplier", Decimal("0.0"), actor_id=None)

    primary = create_soldier(admin_session, personal_number="score-proj-01")
    replacement = create_soldier(admin_session, personal_number="score-proj-02")
    primary.enrolled_at = date(2026, 4, 1)
    replacement.enrolled_at = date(2026, 4, 1)
    admin_session.flush()

    duty_type = _duty_type(admin_session, name="score-projection-duty")
    location = _location(admin_session, name="score-projection-location")

    cross_quarter = DutyAssignment(
        soldier_id=primary.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 29),
        end_date=date(2026, 7, 3),
        status="published",
    )
    reserve = DutyAssignment(
        soldier_id=primary.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 13),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 7, 11),
        called_up_to=date(2026, 7, 11),
    )
    admin_session.add_all([cross_quarter, reserve])
    admin_session.flush()

    admin_session.add(
        DutyDayOverride(
            duty_assignment_id=cross_quarter.id,
            date=date(2026, 6, 30),
            reason="replacement",
            effective_soldier_id=replacement.id,
        )
    )
    admin_session.add(
        DutyDismissal(
            duty_assignment_id=cross_quarter.id,
            dismissed_from=date(2026, 7, 1),
            dismissed_to=date(2026, 7, 1),
        )
    )
    admin_session.flush()
    override = admin_session.execute(
        select(DutyDayOverride).where(DutyDayOverride.duty_assignment_id == cross_quarter.id)
    ).scalar_one()
    dismissal = admin_session.execute(
        select(DutyDismissal).where(DutyDismissal.duty_assignment_id == cross_quarter.id)
    ).scalar_one()

    primary_adjustment = create_adjustment(
        admin_session,
        soldier_id=primary.id,
        delta=Decimal("5.00"),
        reason="quarter-bonus",
        actor_id=None,
    )
    primary_adjustment.created_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    replacement_adjustment = create_adjustment(
        admin_session,
        soldier_id=replacement.id,
        delta=Decimal("-0.50"),
        reason="quarter-correction",
        actor_id=None,
    )
    replacement_adjustment.created_at = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)

    _grant_full_coverage_exemption(
        admin_session,
        soldier_id=primary.id,
        start_date=date(2026, 7, 5),
        end_date=date(2026, 7, 20),
    )
    admin_session.flush()

    assert active_days(admin_session, soldier=primary) < (
        date.today() - primary.enrolled_at
    ).days

    return {
        "primary": primary,
        "replacement": replacement,
        "cross_quarter": cross_quarter,
        "reserve": reserve,
        "override": override,
        "dismissal": dismissal,
        "primary_adjustment": primary_adjustment,
        "replacement_adjustment": replacement_adjustment,
        "q2": date(2026, 4, 1),
        "q3": date(2026, 7, 1),
        "planning_start": date(2026, 10, 1),
        "reset_date": date(2026, 4, 1),
    }


def test_project_soldier_bucket_matches_canonical_scoring_contract(admin_session):
    scenario = _seed_projection_scenario(admin_session)

    primary_q2 = project_soldier_bucket(
        admin_session, scenario["primary"].id, scenario["q2"]
    )
    primary_q3 = project_soldier_bucket(
        admin_session, scenario["primary"].id, scenario["q3"]
    )
    replacement_q2 = project_soldier_bucket(
        admin_session, scenario["replacement"].id, scenario["q2"]
    )

    expected_primary_q2 = _canonical_bucket_summary(
        admin_session,
        soldier=scenario["primary"],
        quarter_start_value=scenario["q2"],
        planning_start=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )
    expected_primary_q3 = _canonical_bucket_summary(
        admin_session,
        soldier=scenario["primary"],
        quarter_start_value=scenario["q3"],
        planning_start=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )
    expected_replacement_q2 = _canonical_bucket_summary(
        admin_session,
        soldier=scenario["replacement"],
        quarter_start_value=scenario["q2"],
        planning_start=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )

    assert primary_q2.soldier_id == scenario["primary"].id
    assert primary_q2.quarter_start == scenario["q2"]
    assert (
        primary_q2.duty_score,
        primary_q2.adjustment_score,
        primary_q2.shift_count,
    ) == expected_primary_q2

    assert primary_q3.soldier_id == scenario["primary"].id
    assert primary_q3.quarter_start == scenario["q3"]
    assert (
        primary_q3.duty_score,
        primary_q3.adjustment_score,
        primary_q3.shift_count,
    ) == expected_primary_q3

    assert replacement_q2.soldier_id == scenario["replacement"].id
    assert replacement_q2.quarter_start == scenario["q2"]
    assert (
        replacement_q2.duty_score,
        replacement_q2.adjustment_score,
        replacement_q2.shift_count,
    ) == expected_replacement_q2

    assert primary_q2.duty_score == Decimal("1.00")
    assert primary_q2.adjustment_score == Decimal("0")
    assert primary_q2.shift_count == 1

    assert primary_q3.duty_score == Decimal("2.70")
    assert primary_q3.adjustment_score == Decimal("5.00")
    assert primary_q3.shift_count == 2

    assert replacement_q2.duty_score == Decimal("1.00")
    assert replacement_q2.adjustment_score == Decimal("-0.50")
    assert replacement_q2.shift_count == 1

    primary_q3_duty_ids = {
        entry["assignment_id"] for entry in primary_q3.source_fingerprint["duty_rows"]
    }
    assert primary_q3_duty_ids == {scenario["cross_quarter"].id, scenario["reserve"].id}
    assert scenario["primary_adjustment"].id in {
        entry["adjustment_id"] for entry in primary_q3.source_fingerprint["adjustments"]
    }

    replacement_q2_days = {
        entry["day"] for entry in replacement_q2.source_fingerprint["duty_rows"]
    }
    assert replacement_q2_days == {date(2026, 6, 30)}

    replacement_q2_row = next(iter(replacement_q2.source_fingerprint["duty_rows"]))
    assert replacement_q2_row["override_id"] == scenario["override"].id
    assert replacement_q2_row["override_date"] == date(2026, 6, 30)
    assert replacement_q2_row["override_effective_soldier_id"] == scenario["replacement"].id
    assert replacement_q2_row["override_reason"] == "replacement"

    primary_q3_dismissed_row = next(
        row for row in primary_q3.source_fingerprint["duty_rows"] if row["day"] == date(2026, 7, 1)
    )
    assert primary_q3_dismissed_row["dismissal_id"] == scenario["dismissal"].id
    assert primary_q3_dismissed_row["dismissed_from"] == date(2026, 7, 1)
    assert primary_q3_dismissed_row["dismissed_to"] == date(2026, 7, 1)
    assert primary_q3_dismissed_row["score"] == Decimal("0")


def test_source_fingerprint_changes_when_override_or_dismissal_rows_change(admin_session):
    scenario = _seed_projection_scenario(admin_session)
    third_soldier = create_soldier(admin_session, personal_number="score-proj-03")

    before_replacement_q2 = project_soldier_bucket(
        admin_session, scenario["replacement"].id, scenario["q2"]
    )
    before_primary_q3 = project_soldier_bucket(
        admin_session, scenario["primary"].id, scenario["q3"]
    )

    scenario["override"].effective_soldier_id = third_soldier.id
    scenario["dismissal"].dismissed_to = date(2026, 7, 2)
    admin_session.flush()

    after_replacement_q2 = project_soldier_bucket(
        admin_session, scenario["replacement"].id, scenario["q2"]
    )
    after_third_q2 = project_soldier_bucket(admin_session, third_soldier.id, scenario["q2"])
    after_primary_q3 = project_soldier_bucket(
        admin_session, scenario["primary"].id, scenario["q3"]
    )

    assert before_replacement_q2.source_fingerprint != after_replacement_q2.source_fingerprint
    assert after_replacement_q2.duty_score == Decimal("0")
    assert after_third_q2.source_fingerprint["duty_rows"][0]["override_id"] == scenario["override"].id
    assert after_third_q2.source_fingerprint["duty_rows"][0]["override_effective_soldier_id"] == third_soldier.id

    before_dismissed_row = next(
        row for row in before_primary_q3.source_fingerprint["duty_rows"] if row["day"] == date(2026, 7, 1)
    )
    after_july_second_row = next(
        row for row in after_primary_q3.source_fingerprint["duty_rows"] if row["day"] == date(2026, 7, 2)
    )
    assert before_dismissed_row["dismissed_to"] == date(2026, 7, 1)
    assert after_july_second_row["dismissal_id"] == scenario["dismissal"].id
    assert after_july_second_row["dismissed_to"] == date(2026, 7, 2)
    assert after_primary_q3.duty_score == Decimal("1.70")


def test_project_all_buckets_respects_filters_and_is_rerunnable(admin_session):
    scenario = _seed_projection_scenario(admin_session)

    single_bucket = project_soldier_bucket(
        admin_session, scenario["primary"].id, scenario["q3"]
    )

    filtered = project_all_buckets(
        admin_session,
        soldier_ids={scenario["primary"].id},
        quarter_starts={scenario["q3"]},
    )
    rerun = project_all_buckets(
        admin_session,
        soldier_ids={scenario["primary"].id},
        quarter_starts={scenario["q3"]},
    )
    all_buckets = project_all_buckets(admin_session)

    assert filtered == [single_bucket]
    assert rerun == filtered

    summaries = {
        (
            bucket.soldier_id,
            bucket.quarter_start,
            bucket.duty_score,
            bucket.adjustment_score,
            bucket.shift_count,
        )
        for bucket in all_buckets
    }
    assert summaries == {
        (
            scenario["primary"].id,
            scenario["q2"],
            Decimal("1.00"),
            Decimal("0"),
            1,
        ),
        (
            scenario["primary"].id,
            scenario["q3"],
            Decimal("2.70"),
            Decimal("5.00"),
            2,
        ),
        (
            scenario["replacement"].id,
            scenario["q2"],
            Decimal("1.00"),
            Decimal("-0.50"),
            1,
        ),
    }


def test_full_coverage_exemption_reduces_active_days_used_by_projected_read_contract(admin_session):
    scenario = _seed_projection_scenario(admin_session)

    projected_buckets = project_all_buckets(
        admin_session,
        soldier_ids={scenario["primary"].id},
    )
    projected_cumulative = sum(
        (bucket.duty_score + bucket.adjustment_score for bucket in projected_buckets),
        Decimal("0"),
    )
    expected_exempt_days = 16
    raw_active_days = max(1, (date.today() - scenario["primary"].enrolled_at).days)

    assert projected_cumulative == cumulative_score(admin_session, soldier_id=scenario["primary"].id)
    assert active_days(admin_session, soldier=scenario["primary"]) == raw_active_days - expected_exempt_days
