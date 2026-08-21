from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    ImportSession,
    ScoreProjectionDirtyBucket,
    SoldierQuarterScoreProjection,
)
from app.services.adjustments import create_adjustment
from app.services.assignments import cancel_assignment, clear_day_override, create_assignment, set_day_override
from app.services.effort_score import quarter_start
from app.services.exemption_requests import approve_duty_manager_step, submit_request
from app.services.exemptions import grant_exemption
from app.services.hierarchy_transfers import approve_request, create_request
from app.services.import_sessions import confirm_session
from app.services.reserves import call_up_reserve, dismiss_primary
from app.services.score_projection import (
    projection_is_current,
    project_soldier_bucket,
    rebuild_projection_bucket,
)
from app.services.score_projection_reconciliation import reconcile_score_projection
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_soldier


def _duty_type(session, *, name: str, score: str = "2.00") -> DutyType:
    duty_type = DutyType(name=name, score_per_day=Decimal(score))
    session.add(duty_type)
    session.flush()
    return duty_type


def _location(session, *, name: str) -> DutyLocation:
    location = DutyLocation(name=name)
    session.add(location)
    session.flush()
    return location


def _seed_scoring_settings(session) -> None:
    set_setting(session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None)
    set_setting(session, "scoring.reserve_called_up_multiplier", Decimal("1.3"), actor_id=None)
    set_setting(session, "scoring.dismissed_multiplier", Decimal("0.0"), actor_id=None)


def _projection_summary(session, *, soldier_id, quarter_start_value: date) -> tuple[Decimal, Decimal, int]:
    rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id,
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
        )
    ).scalars().all()
    assert rows
    duty_score = sum((row.duty_score for row in rows), Decimal("0"))
    adjustment_score = sum((row.adjustment_score for row in rows), Decimal("0"))
    shift_count = len(
        {
            duty_row["assignment_id"]
            for row in rows
            for duty_row in row.source_fingerprint.get("duty_rows", [])
        }
    )
    return (
        duty_score.quantize(Decimal("0.000001")),
        adjustment_score.quantize(Decimal("0.000001")),
        shift_count,
    )


def _canonical_summary(session, *, soldier_id, quarter_start_value: date) -> tuple[Decimal, Decimal, int]:
    bucket = project_soldier_bucket(session, soldier_id, quarter_start_value)
    return (
        bucket.duty_score.quantize(Decimal("0.000001")),
        bucket.adjustment_score.quantize(Decimal("0.000001")),
        bucket.shift_count,
    )


def _assert_persisted_bucket_is_fresh(session, *, soldier_id, quarter_start_value: date) -> None:
    assert _projection_summary(
        session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
    ) == _canonical_summary(session, soldier_id=soldier_id, quarter_start_value=quarter_start_value)
    assert projection_is_current(session, {(soldier_id, quarter_start_value)})


def _dirty_records(session) -> list[ScoreProjectionDirtyBucket]:
    return list(
        session.execute(
            select(ScoreProjectionDirtyBucket).order_by(
                ScoreProjectionDirtyBucket.soldier_id,
                ScoreProjectionDirtyBucket.quarter_start,
            )
        ).scalars()
    )


def test_assignment_publish_and_cancel_refresh_persisted_projection(admin_session):
    _seed_scoring_settings(admin_session)
    soldier = create_soldier(admin_session, personal_number="fresh-publish")
    duty_type = _duty_type(admin_session, name="fresh-publish-duty")
    location = _location(admin_session, name="fresh-publish-location")
    target_quarter = date(2026, 7, 1)

    assignment = create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)

    cancel_assignment(admin_session, assignment=assignment, reason="test")
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("0.000000"), 0)


def test_day_override_set_and_clear_refreshes_old_and_new_soldier_buckets(admin_session):
    _seed_scoring_settings(admin_session)
    primary = create_soldier(admin_session, personal_number="fresh-override-primary")
    replacement = create_soldier(admin_session, personal_number="fresh-override-replacement")
    duty_type = _duty_type(admin_session, name="fresh-override-duty")
    location = _location(admin_session, name="fresh-override-location")
    target_quarter = date(2026, 7, 1)
    assignment = create_assignment(
        admin_session,
        soldier_id=primary.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    admin_session.flush()

    set_day_override(
        admin_session,
        assignment=assignment,
        date=date(2026, 7, 8),
        effective_soldier_id=replacement.id,
        reason="replacement",
    )
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=primary.id, quarter_start_value=target_quarter
    )
    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=replacement.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=primary.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)
    assert _projection_summary(
        admin_session, soldier_id=replacement.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)

    clear_day_override(admin_session, assignment=assignment, date=date(2026, 7, 8))
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=primary.id, quarter_start_value=target_quarter
    )
    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=replacement.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=primary.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)
    assert _projection_summary(
        admin_session, soldier_id=replacement.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("0.000000"), 0)


def test_dismissal_refreshes_assignment_projection_bucket(admin_session):
    _seed_scoring_settings(admin_session)
    soldier = create_soldier(admin_session, personal_number="fresh-dismiss")
    duty_type = _duty_type(admin_session, name="fresh-dismiss-duty")
    location = _location(admin_session, name="fresh-dismiss-location")
    target_quarter = date(2026, 7, 1)
    assignment = create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    admin_session.flush()

    dismiss_primary(
        admin_session,
        assignment=assignment,
        from_date=date(2026, 7, 8),
        to_date=date(2026, 7, 8),
        reason="released",
    )
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)


def test_reserve_call_up_refreshes_reserve_projection_bucket(admin_session):
    _seed_scoring_settings(admin_session)
    soldier = create_soldier(admin_session, personal_number="fresh-reserve")
    duty_type = _duty_type(admin_session, name="fresh-reserve-duty")
    location = _location(admin_session, name="fresh-reserve-location")
    target_quarter = date(2026, 7, 1)
    assignment = create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
        is_reserve=True,
    )
    admin_session.flush()

    call_up_reserve(
        admin_session,
        assignment=assignment,
        from_date=date(2026, 7, 8),
        to_date=date(2026, 7, 8),
    )
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("3.000000"), Decimal("0.000000"), 1)


def test_adjustment_refreshes_created_at_quarter_projection_bucket(admin_session):
    soldier = create_soldier(admin_session, personal_number="fresh-adjustment")
    adjustment = create_adjustment(
        admin_session,
        soldier_id=soldier.id,
        delta=Decimal("7.50"),
        reason="manual correction",
    )
    admin_session.flush()
    admin_session.refresh(adjustment)
    target_quarter = quarter_start(adjustment.created_at.date())

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _projection_summary(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("7.500000"), 0)


def test_exemption_grant_and_approval_refresh_existing_assignment_quarters(admin_session):
    _seed_scoring_settings(admin_session)
    soldier = create_soldier(admin_session, personal_number="fresh-exemption")
    approver = create_soldier(admin_session, personal_number="fresh-exemption-dm")
    duty_type = _duty_type(admin_session, name="fresh-exemption-duty")
    location = _location(admin_session, name="fresh-exemption-location")
    exemption_type = ExemptionType(name="fresh-exemption-type")
    admin_session.add(exemption_type)
    admin_session.flush()
    admin_session.add(
        ExemptionDutyTypeMap(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
    )
    assignment = create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    target_quarter = date(2026, 7, 1)
    rebuild_projection_bucket(admin_session, soldier.id, target_quarter)
    admin_session.flush()

    grant_exemption(
        admin_session,
        soldier_id=soldier.id,
        exemption_type_id=exemption_type.id,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        reason="medical",
    )
    request = submit_request(
        admin_session,
        soldier.id,
        exemption_type.id,
        date(2026, 8, 1),
        date(2026, 8, 3),
        "official",
    )
    request.status = "pending_duty_manager"
    approve_duty_manager_step(admin_session, request.id, approver.id)
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert projection_is_current(admin_session, {(soldier.id, date(2026, 7, 1)), (soldier.id, date(2026, 8, 1))})


def test_hierarchy_transfer_refreshes_existing_projection_and_records_old_new_nodes(admin_session):
    _seed_scoring_settings(admin_session)
    old_node = create_node(admin_session, level="branch", name="fresh-transfer-old")
    new_node = create_node(admin_session, level="branch", name="fresh-transfer-new")
    actor = create_soldier(admin_session, personal_number="fresh-transfer-actor")
    soldier = create_soldier(
        admin_session, personal_number="fresh-transfer-soldier", hierarchy_node_id=old_node.id
    )
    duty_type = _duty_type(admin_session, name="fresh-transfer-duty")
    location = _location(admin_session, name="fresh-transfer-location")
    target_quarter = date(2026, 7, 1)
    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    request = create_request(
        admin_session, soldier_id=soldier.id, to_node_id=new_node.id, requested_by=actor.id
    )
    approve_request(admin_session, request_id=request.id, actor_id=actor.id)
    admin_session.flush()

    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    records = _dirty_records(admin_session)
    assert any(
        record.soldier_id == soldier.id
        and record.quarter_start == target_quarter
        and str(old_node.id) in record.old_node_ids
        and str(new_node.id) in record.new_node_ids
        for record in records
    )


def test_import_commit_refreshes_assignment_projection_bucket(admin_session):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-import-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-import-soldier")
    duty_type = _duty_type(admin_session, name="fresh-import-duty")
    location = _location(admin_session, name="fresh-import-location")
    shift = DutyShift(
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
        required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()
    import_session = ImportSession(
        filename="fresh.xlsx",
        raw_excel=b"",
        created_by=actor.id,
        parsed_state={
            "assignments": [
                {
                    "row": 2,
                    "action": "new",
                    "resolved_soldier_id": str(soldier.id),
                    "resolved_duty_shift_id": str(shift.id),
                    "is_reserve": False,
                    "notes": "from import",
                }
            ]
        },
        user_selections={},
    )
    admin_session.add(import_session)
    admin_session.flush()

    result = confirm_session(admin_session, session_id=import_session.id, actor=actor)
    admin_session.flush()

    assert result["errors"] == []
    assert admin_session.execute(select(DutyAssignment)).scalar_one().soldier_id == soldier.id
    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=date(2026, 7, 1)
    )


def test_reconciliation_repairs_dirty_bucket_and_records_divergence(admin_session):
    _seed_scoring_settings(admin_session)
    soldier = create_soldier(admin_session, personal_number="fresh-reconcile")
    duty_type = _duty_type(admin_session, name="fresh-reconcile-duty")
    location = _location(admin_session, name="fresh-reconcile-location")
    target_quarter = date(2026, 7, 1)
    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier.id,
            SoldierQuarterScoreProjection.quarter_start == target_quarter,
            SoldierQuarterScoreProjection.duty_type_id == duty_type.id,
        )
    ).scalars().all()
    assert rows
    rows[0].duty_score = Decimal("0.000000")
    dirty = admin_session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == soldier.id,
            ScoreProjectionDirtyBucket.quarter_start == target_quarter,
        )
    ).scalar_one()
    dirty.status = "dirty"
    admin_session.flush()

    result = reconcile_score_projection(admin_session)
    admin_session.flush()

    assert result == {"checked": 1, "repaired": 1, "diverged": 1}
    assert dirty.status == "current"
    assert dirty.divergence is not None
    _assert_persisted_bucket_is_fresh(
        admin_session, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
