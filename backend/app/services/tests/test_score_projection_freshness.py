from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import AlgorithmJob
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
from app.routes.algorithm import (
    BulkAcceptRequest,
    accept_proposal,
    accept_proposal_direct,
    bulk_accept_proposals,
    reset_published_assignments,
)
from app.services.adjustments import create_adjustment
from app.services.assignments import cancel_assignment, clear_day_override, create_assignment, set_day_override
from app.services.effort_score import quarter_start
from app.services.exemption_requests import approve_duty_manager_step, submit_request
from app.services.exemptions import grant_exemption, revoke_exemption
from app.services.hierarchy_transfers import approve_request, create_request
from app.services.import_sessions import confirm_session
from app.services.reserves import call_up_reserve, delete_dismissal, dismiss_primary
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


def _assert_committed_bucket_is_fresh(admin_engine, *, soldier_id, quarter_start_value: date) -> None:
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as session:
        _assert_persisted_bucket_is_fresh(
            session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
        )


def _committed_projection_summary(admin_engine, *, soldier_id, quarter_start_value: date):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as session:
        return _projection_summary(session, soldier_id=soldier_id, quarter_start_value=quarter_start_value)


def _dirty_records(session) -> list[ScoreProjectionDirtyBucket]:
    return list(
        session.execute(
            select(ScoreProjectionDirtyBucket).order_by(
                ScoreProjectionDirtyBucket.soldier_id,
                ScoreProjectionDirtyBucket.quarter_start,
            )
        ).scalars()
    )


def _draft_algorithm_assignment(session, *, soldier_id, duty_type_id, duty_location_id, start_date, end_date):
    assignment = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        status="algorithm_draft",
    )
    session.add(assignment)
    session.flush()
    return assignment


def _algorithm_job(session, *, actor_id=None):
    job = AlgorithmJob(
        planning_start=date(2026, 7, 1),
        planning_end=date(2026, 7, 31),
        shift_ids=[],
        settings_json={},
        mode="full",
        status="done",
        created_by=actor_id,
    )
    session.add(job)
    session.flush()
    return job


def test_assignment_publish_and_cancel_refresh_persisted_projection(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("0.000000"), 0)


def test_algorithm_proposal_accept_route_refreshes_committed_projection(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-algo-accept-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-algo-accept")
    duty_type = _duty_type(admin_session, name="fresh-algo-accept-duty")
    location = _location(admin_session, name="fresh-algo-accept-location")
    target_quarter = date(2026, 7, 1)
    job = _algorithm_job(admin_session, actor_id=actor.id)
    assignment = _draft_algorithm_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    assignment.algorithm_job_id = job.id

    accept_proposal(job.id, assignment.id, session=admin_session, user=actor)

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)


def test_algorithm_bulk_accept_route_refreshes_committed_projection(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-algo-bulk-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-algo-bulk")
    duty_type = _duty_type(admin_session, name="fresh-algo-bulk-duty")
    location = _location(admin_session, name="fresh-algo-bulk-location")
    target_quarter = date(2026, 7, 1)
    job = _algorithm_job(admin_session, actor_id=actor.id)
    assignment = _draft_algorithm_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 11),
        end_date=date(2026, 7, 13),
    )
    assignment.algorithm_job_id = job.id

    bulk_accept_proposals(
        job.id,
        BulkAcceptRequest(assignment_ids=[assignment.id]),
        session=admin_session,
        user=actor,
    )

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)


def test_algorithm_direct_accept_route_refreshes_committed_projection(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-algo-direct-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-algo-direct")
    duty_type = _duty_type(admin_session, name="fresh-algo-direct-duty")
    location = _location(admin_session, name="fresh-algo-direct-location")
    target_quarter = date(2026, 7, 1)
    assignment = _draft_algorithm_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 14),
        end_date=date(2026, 7, 16),
    )

    accept_proposal_direct(assignment.id, session=admin_session, user=actor)

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)


def test_algorithm_reset_published_route_refreshes_cancelled_projection(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-algo-reset-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-algo-reset")
    duty_type = _duty_type(admin_session, name="fresh-algo-reset-duty")
    location = _location(admin_session, name="fresh-algo-reset-location")
    target_quarter = date(2027, 1, 1)
    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2027, 1, 8),
        end_date=date(2027, 1, 10),
    )
    admin_session.flush()

    reset_published_assignments(days_ahead=0, session=admin_session, user=actor)

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("0.000000"), 0)


def test_assignment_interval_refreshes_every_touched_quarter(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    soldier = create_soldier(admin_session, personal_number="fresh-interval")
    duty_type = _duty_type(admin_session, name="fresh-interval-duty")
    location = _location(admin_session, name="fresh-interval-location")

    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 1, 15),
        end_date=date(2026, 10, 15),
    )
    admin_session.commit()

    for target_quarter in (date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)):
        _assert_committed_bucket_is_fresh(
            admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
        )
        assert _committed_projection_summary(
            admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
        )[2] == 1


def test_day_override_set_and_clear_refreshes_old_and_new_soldier_buckets(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=primary.id, quarter_start_value=target_quarter
    )
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=replacement.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=primary.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)
    assert _committed_projection_summary(
        admin_engine, soldier_id=replacement.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)

    clear_day_override(admin_session, assignment=assignment, date=date(2026, 7, 8))
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=primary.id, quarter_start_value=target_quarter
    )
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=replacement.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=primary.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)
    assert _committed_projection_summary(
        admin_engine, soldier_id=replacement.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("0.000000"), 0)


def test_dismissal_refreshes_assignment_projection_bucket(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)


def test_reserve_dismissal_delete_refreshes_committed_projection(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-dismiss-delete-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-dismiss-delete")
    duty_type = _duty_type(admin_session, name="fresh-dismiss-delete-duty")
    location = _location(admin_session, name="fresh-dismiss-delete-location")
    target_quarter = date(2026, 7, 1)
    assignment = create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    dismissal = dismiss_primary(
        admin_session,
        assignment=assignment,
        from_date=date(2026, 7, 8),
        to_date=date(2026, 7, 8),
        reason="released",
        actor_id=actor.id,
    )
    admin_session.commit()
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("2.000000"), Decimal("0.000000"), 1)

    delete_dismissal(admin_session, dismissal=dismissal, actor_id=actor.id)
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)


def test_reserve_call_up_refreshes_reserve_projection_bucket(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("3.000000"), Decimal("0.000000"), 1)


def test_adjustment_refreshes_created_at_quarter_projection_bucket(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("7.500000"), 0)


def test_exemption_grant_and_approval_refresh_existing_assignment_quarters(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=date(2026, 7, 1)
    )


def test_exemption_revoke_refreshes_committed_projection(admin_session, admin_engine):
    _seed_scoring_settings(admin_session)
    actor = create_soldier(admin_session, personal_number="fresh-exemption-revoke-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-exemption-revoke")
    duty_type = _duty_type(admin_session, name="fresh-exemption-revoke-duty")
    location = _location(admin_session, name="fresh-exemption-revoke-location")
    exemption_type = ExemptionType(name="fresh-exemption-revoke-type")
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
        start_date=date(2027, 1, 8),
        end_date=date(2027, 1, 10),
    )
    exemption = grant_exemption(
        admin_session,
        soldier_id=soldier.id,
        exemption_type_id=exemption_type.id,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        reason="future medical",
        actor_id=actor.id,
    )
    admin_session.commit()
    target_quarter = date(2027, 1, 1)
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier.id,
            SoldierQuarterScoreProjection.quarter_start == target_quarter,
        )
    ).scalars().all()
    assert rows
    rows[0].duty_score = Decimal("99.000000")
    admin_session.commit()

    revoke_exemption(
        admin_session,
        exemption_id=exemption.id,
        reason="no longer needed",
        actor_id=actor.id,
    )
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)


def test_hierarchy_transfer_refreshes_existing_projection_and_records_old_new_nodes(admin_session, admin_engine):
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
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
    records = _dirty_records(admin_session)
    assert any(
        record.soldier_id == soldier.id
        and record.quarter_start == target_quarter
        and str(old_node.id) in record.old_node_ids
        and str(new_node.id) in record.new_node_ids
        for record in records
    )


def test_import_commit_refreshes_assignment_projection_bucket(admin_session, admin_engine):
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
    admin_session.commit()

    assert result["errors"] == []
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=date(2026, 7, 1)
    )


def test_reconciliation_repairs_dirty_bucket_and_records_divergence(admin_session, admin_engine):
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
    admin_session.commit()

    assert result == {"checked": 1, "repaired": 1, "diverged": 1}
    assert dirty.status == "current"
    assert dirty.divergence is not None
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier.id, quarter_start_value=target_quarter
    )
