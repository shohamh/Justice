from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    AlgorithmJob,
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyShift,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    ImportSession,
    ScoreProjectionDirtyBucket,
    SoldierQuarterScoreProjection,
    SystemSetting,
)
from app.routes.algorithm import (
    BulkAcceptRequest,
    accept_proposal,
    accept_proposal_direct,
    bulk_accept_proposals,
    reset_published_assignments,
)
from app.services import score_projection, score_projection_reconciliation, scoring
from app.services.adjustments import create_adjustment
from app.services.assignments import (
    cancel_assignment,
    clear_day_override,
    create_assignment,
    replace_assignment,
    set_day_override,
)
from app.services.duty_config import update_duty_type
from app.services.effort_score import quarter_start
from app.services.exemption_requests import approve_duty_manager_step, submit_request
from app.services.exemptions import grant_exemption, revoke_exemption
from app.services.hierarchy_transfers import approve_request, create_request
from app.services.import_sessions import confirm_session
from app.services.reserves import call_up_reserve, delete_dismissal, dismiss_primary
from app.services.score_projection import (
    SCORE_PROJECTION_MAINTENANCE_LOCK_KEY,
    backfill_score_projection,
    project_soldier_bucket,
    projection_is_current,
    rebuild_projection_bucket,
    refresh_projection_for_change,
    refresh_projections_for_assignments_bulk,
)
from app.services.score_projection_reconciliation import reconcile_score_projection
from app.services.settings_loader import get_setting, set_setting
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


def _complete_score_projection_backfill(session) -> None:
    state = backfill_score_projection(session)
    while not state.backfill_complete:
        state = backfill_score_projection(session)


def _canonical(value):
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.000001"))
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _transparency_row_by_soldier(result, soldier_id):
    return next(row for row in result["rows"] if row["soldier_id"] == soldier_id)


def test_duty_type_score_change_repairs_projected_transparency_before_returning(admin_session):
    _seed_scoring_settings(admin_session)
    admin = create_soldier(admin_session, personal_number="fresh-config-score-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="fresh-config-score-soldier")
    duty_type = _duty_type(admin_session, name="fresh-config-score-duty", score="0.00")
    location = _location(admin_session, name="fresh-config-score-location")
    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    _complete_score_projection_backfill(admin_session)

    before = scoring.transparency_rows(admin_session, viewer=admin)
    assert _transparency_row_by_soldier(before, soldier.id)["cumulative_score"] == Decimal("0.000000")

    update_duty_type(
        admin_session,
        duty_type=duty_type,
        name=None,
        score_per_day=Decimal("4.00"),
        description=None,
    )

    required = {(soldier.id, date(2026, 7, 1))}
    assert not projection_is_current(admin_session, required)
    legacy = scoring._legacy_transparency_rows(admin_session, viewer=admin)
    projected = scoring.transparency_rows(admin_session, viewer=admin)

    assert _canonical(projected) == _canonical(legacy)
    assert _transparency_row_by_soldier(projected, soldier.id)["cumulative_score"] == Decimal("8.000000")
    assert projection_is_current(admin_session, required)
    assert _projection_summary(
        admin_session, soldier_id=soldier.id, quarter_start_value=date(2026, 7, 1)
    )[0] == Decimal("8.000000")


@pytest.mark.parametrize(
    (
        "source",
        "setting_key",
        "old_multiplier",
        "new_multiplier",
        "is_reserve",
        "called_up",
        "dismissed_day",
        "expected_score",
    ),
    [
        (
            "reserve_standby",
            "scoring.reserve_standby_multiplier",
            Decimal("0.2"),
            Decimal("0.5"),
            True,
            False,
            False,
            Decimal("3.000000"),
        ),
        (
            "reserve_called_up",
            "scoring.reserve_called_up_multiplier",
            Decimal("1.3"),
            Decimal("2.3"),
            True,
            True,
            False,
            Decimal("5.400000"),
        ),
        (
            "dismissal",
            "scoring.dismissed_multiplier",
            Decimal("0.0"),
            Decimal("0.5"),
            False,
            False,
            True,
            Decimal("5.000000"),
        ),
    ],
)
def test_scoring_multiplier_change_repairs_only_affected_projection_rows_before_returning(
    admin_session,
    source,
    setting_key,
    old_multiplier,
    new_multiplier,
    is_reserve,
    called_up,
    dismissed_day,
    expected_score,
):
    _seed_scoring_settings(admin_session)
    admin = create_soldier(
        admin_session, personal_number=f"fresh-mult-admin-{source}", role="admin"
    )
    affected = create_soldier(admin_session, personal_number=f"fresh-mult-affected-{source}")
    unaffected = create_soldier(admin_session, personal_number=f"fresh-mult-other-{source}")
    duty_type = _duty_type(admin_session, name=f"fresh-mult-duty-{source}", score="2.00")
    location = _location(admin_session, name=f"fresh-mult-location-{source}")
    assignment = DutyAssignment(
        soldier_id=affected.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 13),
        status="published",
        is_reserve=is_reserve,
        called_up_from=date(2026, 7, 11) if called_up else None,
        called_up_to=date(2026, 7, 11) if called_up else None,
    )
    unaffected_assignment = DutyAssignment(
        soldier_id=unaffected.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 12),
        status="published",
    )
    admin_session.add_all([assignment, unaffected_assignment])
    admin_session.flush()
    if dismissed_day:
        admin_session.add(
            DutyDismissal(
                duty_assignment_id=assignment.id,
                dismissed_from=date(2026, 7, 11),
                dismissed_to=date(2026, 7, 11),
            )
        )
        admin_session.flush()
    refresh_projection_for_change(
        admin_session,
        soldier_ids={affected.id, unaffected.id},
        affected_dates={date(2026, 7, 10), date(2026, 7, 11), date(2026, 7, 12)},
    )
    _complete_score_projection_backfill(admin_session)

    baseline = scoring.transparency_rows(admin_session, viewer=admin)
    before_score = _transparency_row_by_soldier(baseline, affected.id)["cumulative_score"]
    unaffected_before = _transparency_row_by_soldier(baseline, unaffected.id)["cumulative_score"]

    affected_key = {(affected.id, date(2026, 7, 1))}
    unaffected_key = {(unaffected.id, date(2026, 7, 1))}
    set_setting(admin_session, setting_key, old_multiplier, actor_id=None)
    assert projection_is_current(admin_session, affected_key)

    set_setting(admin_session, setting_key, new_multiplier, actor_id=None)

    assert not projection_is_current(admin_session, affected_key)
    assert projection_is_current(admin_session, unaffected_key)

    legacy = scoring._legacy_transparency_rows(admin_session, viewer=admin)
    projected = scoring.transparency_rows(admin_session, viewer=admin)

    assert _canonical(projected) == _canonical(legacy)
    assert before_score != expected_score
    assert _transparency_row_by_soldier(projected, affected.id)["cumulative_score"] == expected_score
    assert _transparency_row_by_soldier(projected, unaffected.id)["cumulative_score"] == unaffected_before
    assert projection_is_current(admin_session, affected_key | unaffected_key)


def test_multiplier_setting_change_serializes_with_projection_maintenance_lock(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    lock_attempted = Event()
    write_finished = Event()
    errors = []

    def observe_lock_attempt(_connection, _cursor, statement, _parameters, _context, _executemany):
        if (
            current_thread().name == "score-setting-writer"
            and "pg_advisory_xact_lock" in statement.lower()
        ):
            lock_attempted.set()

    def update_multiplier():
        try:
            with SessionLocal() as writer_session:
                set_setting(
                    writer_session,
                    "scoring.reserve_called_up_multiplier",
                    Decimal("2.3"),
                    actor_id=None,
                )
                writer_session.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            write_finished.set()

    event.listen(admin_engine, "before_cursor_execute", observe_lock_attempt)
    writer = None
    with SessionLocal() as maintenance_session:
        maintenance_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": SCORE_PROJECTION_MAINTENANCE_LOCK_KEY},
        )
        writer = Thread(target=update_multiplier, name="score-setting-writer")
        writer.start()
        try:
            assert lock_attempted.wait(timeout=5)
            assert not write_finished.wait(timeout=0.15)
        finally:
            maintenance_session.commit()
            writer.join(timeout=10)
            event.remove(admin_engine, "before_cursor_execute", observe_lock_attempt)

    assert writer is not None and not writer.is_alive()
    assert write_finished.is_set()
    assert not errors


@pytest.mark.parametrize("refresh_mode", ["single", "bulk"])
def test_reserve_assignment_refresh_waits_for_multiplier_invalidation(admin_engine, refresh_mode):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        soldier = create_soldier(
            setup_session, personal_number=f"fresh-config-lock-reserve-{refresh_mode}"
        )
        duty_type = _duty_type(
            setup_session, name=f"fresh-config-lock-reserve-duty-{refresh_mode}"
        )
        location = _location(
            setup_session, name=f"fresh-config-lock-reserve-location-{refresh_mode}"
        )
        assignment = create_assignment(
            setup_session,
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 9),
            is_reserve=True,
        )
        _complete_score_projection_backfill(setup_session)
        setup_session.commit()
        soldier_id = soldier.id
        assignment_id = assignment.id

    lock_attempted = Event()
    write_finished = Event()
    errors = []

    def observe_shared_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if (
            current_thread().name == "assignment-projection-writer"
            and "pg_advisory_xact_lock_shared" in statement.lower()
        ):
            lock_attempted.set()

    def call_up_assignment():
        try:
            with SessionLocal() as writer_session:
                current_assignment = writer_session.get(DutyAssignment, assignment_id)
                cached_settings = [
                    writer_session.get(SystemSetting, key)
                    for key in (
                        "scoring.reserve_standby_multiplier",
                        "scoring.reserve_called_up_multiplier",
                        "scoring.dismissed_multiplier",
                    )
                ]
                for setting_key in (
                    "scoring.reserve_standby_multiplier",
                    "scoring.reserve_called_up_multiplier",
                    "scoring.dismissed_multiplier",
                ):
                    get_setting(writer_session, setting_key)
                assert all(row is not None for row in cached_settings)
                if refresh_mode == "single":
                    call_up_reserve(
                        writer_session,
                        assignment=current_assignment,
                        from_date=date(2026, 7, 8),
                        to_date=date(2026, 7, 8),
                    )
                else:
                    current_assignment.called_up_from = date(2026, 7, 8)
                    current_assignment.called_up_to = date(2026, 7, 8)
                    writer_session.flush()
                    refresh_projections_for_assignments_bulk(
                        writer_session, assignments=[current_assignment]
                    )
                writer_session.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            write_finished.set()

    event.listen(admin_engine, "before_cursor_execute", observe_shared_lock)
    writer = None
    with SessionLocal() as config_session:
        set_setting(
            config_session,
            "scoring.reserve_called_up_multiplier",
            Decimal("2.3"),
            actor_id=None,
        )
        writer = Thread(target=call_up_assignment, name="assignment-projection-writer")
        writer.start()
        try:
            assert lock_attempted.wait(timeout=5), "assignment refresh did not request the shared maintenance lock"
            assert not write_finished.wait(timeout=0.15)
        finally:
            config_session.commit()
            writer.join(timeout=10)
            event.remove(admin_engine, "before_cursor_execute", observe_shared_lock)

    assert writer is not None and not writer.is_alive()
    assert write_finished.is_set()
    assert not errors
    with SessionLocal() as verify_session:
        assert _projection_summary(
            verify_session, soldier_id=soldier_id, quarter_start_value=date(2026, 7, 1)
        )[0] == Decimal("4.600000")
        assert projection_is_current(verify_session, {(soldier_id, date(2026, 7, 1))})


def test_assignment_refresh_uses_new_duty_type_score_after_config_wait(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        soldier = create_soldier(setup_session, personal_number="fresh-config-lock-type-score")
        duty_type = _duty_type(setup_session, name="fresh-config-lock-type-score-duty")
        location = _location(setup_session, name="fresh-config-lock-type-score-location")
        create_assignment(
            setup_session,
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 10),
        )
        _complete_score_projection_backfill(setup_session)
        setup_session.commit()
        soldier_id = soldier.id
        duty_type_id = duty_type.id

    shared_lock_attempted = Event()
    writer_preloaded_type = Event()
    write_finished = Event()
    errors = []

    def observe_shared_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if (
            current_thread().name == "type-score-projection-writer"
            and "pg_advisory_xact_lock_shared" in statement.lower()
        ):
            shared_lock_attempted.set()

    def rebuild_assignment_bucket():
        try:
            with SessionLocal() as writer_session:
                cached_type = writer_session.get(DutyType, duty_type_id)
                assert cached_type.score_per_day == Decimal("2.00")
                writer_preloaded_type.set()
                refresh_projection_for_change(
                    writer_session,
                    soldier_ids={soldier_id},
                    affected_dates={date(2026, 7, 8), date(2026, 7, 9)},
                )
                writer_session.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            write_finished.set()

    event.listen(admin_engine, "before_cursor_execute", observe_shared_lock)
    writer = None
    with SessionLocal() as config_session:
        configured_type = config_session.get(DutyType, duty_type_id)
        update_duty_type(
            config_session,
            duty_type=configured_type,
            name=None,
            score_per_day=Decimal("4.00"),
            description=None,
        )
        writer = Thread(target=rebuild_assignment_bucket, name="type-score-projection-writer")
        writer.start()
        try:
            assert writer_preloaded_type.wait(timeout=5)
            assert shared_lock_attempted.wait(timeout=5)
            assert not write_finished.wait(timeout=0.15)
        finally:
            config_session.commit()
            writer.join(timeout=10)
            event.remove(admin_engine, "before_cursor_execute", observe_shared_lock)

    assert writer is not None and not writer.is_alive()
    assert write_finished.is_set()
    assert not errors
    with SessionLocal() as verify_session:
        assert _projection_summary(
            verify_session, soldier_id=soldier_id, quarter_start_value=date(2026, 7, 1)
        )[0] == Decimal("8.000000")
        assert projection_is_current(verify_session, {(soldier_id, date(2026, 7, 1))})


def test_transparency_repair_uses_fresh_multiplier_after_setting_was_cached(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        soldier = create_soldier(setup_session, personal_number="fresh-cached-multiplier-repair")
        duty_type = _duty_type(setup_session, name="fresh-cached-multiplier-repair-duty")
        location = _location(setup_session, name="fresh-cached-multiplier-repair-location")
        create_assignment(
            setup_session,
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 11),
            is_reserve=True,
        )
        _complete_score_projection_backfill(setup_session)
        setup_session.commit()
        soldier_id = soldier.id

    settings_loaded = Event()
    continue_read = Event()
    result = []
    errors = []

    def read_transparency():
        try:
            with SessionLocal() as read_session:
                cached_settings = [
                    read_session.get(SystemSetting, key)
                    for key in (
                        "scoring.reserve_standby_multiplier",
                        "scoring.reserve_called_up_multiplier",
                        "scoring.dismissed_multiplier",
                    )
                ]
                for setting_key in (
                    "scoring.reserve_standby_multiplier",
                    "scoring.reserve_called_up_multiplier",
                    "scoring.dismissed_multiplier",
                ):
                    get_setting(read_session, setting_key)
                settings_loaded.set()
                if not continue_read.wait(timeout=10):
                    raise TimeoutError("test did not release the cached-setting transparency read")
                projected = scoring.transparency_rows(read_session)
                assert all(row is not None for row in cached_settings)
                result.append(
                    _transparency_row_by_soldier(projected, soldier_id)["cumulative_score"]
                )
                read_session.commit()
        except Exception as exc:
            errors.append(exc)

    reader = Thread(target=read_transparency, name="cached-setting-transparency-reader")
    reader.start()
    try:
        assert settings_loaded.wait(timeout=5)
        with SessionLocal() as config_session:
            set_setting(
                config_session,
                "scoring.reserve_standby_multiplier",
                Decimal("0.5"),
                actor_id=None,
            )
            config_session.commit()
    finally:
        continue_read.set()
        reader.join(timeout=10)

    assert not reader.is_alive()
    assert not errors
    assert result == [Decimal("3.000000")]
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=soldier_id, quarter_start_value=date(2026, 7, 1)
    )


def test_projection_multiplier_inputs_reload_cached_settings(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    multiplier_updates = {
        "scoring.reserve_standby_multiplier": ("0.2", Decimal("0.5")),
        "scoring.reserve_called_up_multiplier": ("1.3", Decimal("2.3")),
        "scoring.dismissed_multiplier": ("0.0", Decimal("0.7")),
    }
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        setup_session.commit()

    with SessionLocal() as read_session:
        cached_settings = [
            read_session.get(SystemSetting, key) for key in multiplier_updates
        ]
        for key, (old_value, _new_value) in multiplier_updates.items():
            assert scoring._get_multiplier_setting(read_session, key, old_value) == Decimal(old_value)

        with SessionLocal() as config_session:
            for key, (_old_value, new_value) in multiplier_updates.items():
                set_setting(config_session, key, new_value, actor_id=None)
            config_session.commit()

        assert all(row is not None for row in cached_settings)
        for key, (_old_value, new_value) in multiplier_updates.items():
            assert scoring._get_multiplier_setting(read_session, key, "0") == new_value


def test_standalone_backfill_waits_for_maintenance_lock(admin_engine, monkeypatch):
    from app.db import session as db_session
    from app.scripts import score_projection as score_projection_script

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", SessionLocal)
    monkeypatch.setattr(sys, "argv", ["score_projection", "--batch-size", "1"])

    lock_attempted = Event()
    batch_started = Event()
    errors = []

    def backfill_batch(_session, **_kwargs):
        batch_started.set()
        return SimpleNamespace(
            canonical_version="1",
            backfill_complete=True,
            resume_after_soldier_id=None,
            resume_after_quarter_start=None,
        )

    monkeypatch.setattr(score_projection, "backfill_score_projection", backfill_batch)

    def observe_cli_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if (
            current_thread().name == "standalone-score-projection-backfill"
            and "pg_advisory_xact_lock(" in statement.lower()
        ):
            lock_attempted.set()

    def run_cli():
        try:
            score_projection_script.main()
        except Exception as exc:
            errors.append(exc)

    event.listen(admin_engine, "before_cursor_execute", observe_cli_lock)
    cli = None
    with SessionLocal() as maintenance_session:
        score_projection.lock_score_projection_maintenance(maintenance_session)
        cli = Thread(target=run_cli, name="standalone-score-projection-backfill")
        cli.start()
        try:
            assert lock_attempted.wait(timeout=5), "standalone backfill did not request the maintenance lock"
            assert not batch_started.wait(timeout=0.15)
        finally:
            maintenance_session.commit()
            cli.join(timeout=10)
            event.remove(admin_engine, "before_cursor_execute", observe_cli_lock)

    assert cli is not None and not cli.is_alive()
    assert not errors
    assert batch_started.is_set()


@pytest.mark.parametrize("repair_path", ["transparency", "repair_keys", "reconciliation"])
def test_config_invalidation_waits_for_projection_read_repair(admin_engine, monkeypatch, repair_path):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        soldier = create_soldier(
            setup_session, personal_number=f"fresh-config-repair-soldier-{repair_path}"
        )
        duty_type = _duty_type(setup_session, name=f"fresh-config-repair-duty-{repair_path}")
        location = _location(setup_session, name=f"fresh-config-repair-location-{repair_path}")
        create_assignment(
            setup_session,
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 10),
            is_reserve=True,
        )
        _complete_score_projection_backfill(setup_session)
        key = (soldier.id, date(2026, 7, 1))
        marker = setup_session.execute(
            select(ScoreProjectionDirtyBucket).where(
                ScoreProjectionDirtyBucket.soldier_id == key[0],
                ScoreProjectionDirtyBucket.quarter_start == key[1],
            )
        ).scalar_one()
        marker.status = "dirty"
        setup_session.commit()
        soldier_id = soldier.id

    rebuild_paused = Event()
    allow_rebuild = Event()
    invalidation_lock_attempted = Event()
    invalidation_finished = Event()
    errors = []
    original_rebuild = score_projection.rebuild_projection_bucket

    def pause_after_rebuild(session, rebuilt_soldier_id, quarter_start_value, **kwargs):
        rows = original_rebuild(session, rebuilt_soldier_id, quarter_start_value, **kwargs)
        if current_thread().name == "score-projection-repair":
            rebuild_paused.set()
            if not allow_rebuild.wait(timeout=10):
                raise TimeoutError("test did not release the paused projection repair")
        return rows

    def observe_invalidation_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if (
            current_thread().name == "score-projection-invalidator"
            and "pg_advisory_xact_lock" in statement.lower()
        ):
            invalidation_lock_attempted.set()

    monkeypatch.setattr(score_projection, "rebuild_projection_bucket", pause_after_rebuild)
    monkeypatch.setattr(
        score_projection_reconciliation, "rebuild_projection_bucket", pause_after_rebuild
    )

    def repair_projection():
        try:
            with SessionLocal() as repair_session:
                if repair_path == "transparency":
                    scoring.transparency_rows(repair_session)
                elif repair_path == "repair_keys":
                    score_projection._repair_projection_keys(repair_session, keys={key})
                else:
                    score_projection_reconciliation.reconcile_score_projection(repair_session)
                repair_session.commit()
        except Exception as exc:
            errors.append(exc)

    def change_multiplier():
        try:
            with SessionLocal() as config_session:
                set_setting(
                    config_session,
                    "scoring.reserve_standby_multiplier",
                    Decimal("0.5"),
                    actor_id=None,
                )
                config_session.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            invalidation_finished.set()

    event.listen(admin_engine, "before_cursor_execute", observe_invalidation_lock)
    repairer = Thread(target=repair_projection, name="score-projection-repair")
    invalidator = None
    repairer.start()
    try:
        assert rebuild_paused.wait(timeout=5), "read did not enter projection repair"
        invalidator = Thread(target=change_multiplier, name="score-projection-invalidator")
        invalidator.start()
        assert invalidation_lock_attempted.wait(timeout=5), "config change did not request exclusive maintenance lock"
        assert not invalidation_finished.wait(timeout=0.15)
    finally:
        allow_rebuild.set()
        repairer.join(timeout=10)
        if invalidator is not None:
            invalidator.join(timeout=10)
        event.remove(admin_engine, "before_cursor_execute", observe_invalidation_lock)

    assert not repairer.is_alive()
    assert invalidator is not None and not invalidator.is_alive()
    assert not errors
    assert invalidation_finished.is_set()
    with SessionLocal() as verify_session:
        marker = verify_session.execute(
            select(ScoreProjectionDirtyBucket).where(
                ScoreProjectionDirtyBucket.soldier_id == soldier_id,
                ScoreProjectionDirtyBucket.quarter_start == date(2026, 7, 1),
            )
        ).scalar_one()
        assert marker.status == "dirty"


def test_reconciliation_orders_partition_and_total_locks_like_writers(admin_engine, monkeypatch):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        soldiers = [
            create_soldier(setup_session, personal_number=f"reconcile-lock-order-{index}")
            for index in range(2)
        ]
        duty_type = _duty_type(setup_session, name="reconcile-lock-order-duty")
        location = _location(setup_session, name="reconcile-lock-order-location")
        assignment_periods = (
            (date(2026, 1, 8), date(2026, 1, 9)),
            (date(2026, 4, 8), date(2026, 4, 9)),
        )
        keys = []
        for soldier, (start_date, end_date) in zip(soldiers, assignment_periods, strict=True):
            create_assignment(
                setup_session,
                soldier_id=soldier.id,
                duty_type_id=duty_type.id,
                duty_location_id=location.id,
                start_date=start_date,
                end_date=end_date,
            )
            keys.append((soldier.id, date(start_date.year, start_date.month, 1)))
        _complete_score_projection_backfill(setup_session)
        for soldier_id, quarter_start_value in keys:
            marker = setup_session.execute(
                select(ScoreProjectionDirtyBucket).where(
                    ScoreProjectionDirtyBucket.soldier_id == soldier_id,
                    ScoreProjectionDirtyBucket.quarter_start == quarter_start_value,
                )
            ).scalar_one()
            marker.status = "dirty"
        setup_session.commit()

    operations = []
    original_rebuild = score_projection_reconciliation.rebuild_projection_bucket
    original_upsert_soldier = score_projection._upsert_soldier_total
    original_upsert_quarter = score_projection._upsert_quarter_total

    def record_rebuild(session, soldier_id, quarter_start_value, **kwargs):
        operations.append(("rebuild", soldier_id, quarter_start_value, kwargs))
        return original_rebuild(session, soldier_id, quarter_start_value, **kwargs)

    def record_soldier_total(session, *, soldier_id):
        operations.append(("soldier_total", soldier_id))
        return original_upsert_soldier(session, soldier_id=soldier_id)

    def record_quarter_total(session, *, quarter_start_value):
        operations.append(("quarter_total", quarter_start_value))
        return original_upsert_quarter(session, quarter_start_value=quarter_start_value)

    def observe_partition_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower()
        if "from soldier_quarter_score_projection" in normalized and "for update" in normalized:
            operations.append(("partition_lock",))

    monkeypatch.setattr(score_projection_reconciliation, "rebuild_projection_bucket", record_rebuild)
    monkeypatch.setattr(score_projection, "_upsert_soldier_total", record_soldier_total)
    monkeypatch.setattr(score_projection, "_upsert_quarter_total", record_quarter_total)
    # The batched implementation imports the total helpers in the reconciliation
    # module; these attributes are absent on the legacy per-bucket path.
    monkeypatch.setattr(
        score_projection_reconciliation, "_upsert_soldier_total", record_soldier_total, raising=False
    )
    monkeypatch.setattr(
        score_projection_reconciliation, "_upsert_quarter_total", record_quarter_total, raising=False
    )
    event.listen(admin_engine, "before_cursor_execute", observe_partition_lock)
    try:
        with SessionLocal() as reconcile_session:
            result = score_projection_reconciliation.reconcile_score_projection(
                reconcile_session, limit=2
            )
    finally:
        event.remove(admin_engine, "before_cursor_execute", observe_partition_lock)

    kinds = [operation[0] for operation in operations]
    assert kinds == [
        "partition_lock",
        "rebuild",
        "rebuild",
        "soldier_total",
        "soldier_total",
        "quarter_total",
        "quarter_total",
    ], f"observed reconciliation lock order: {kinds}"
    expected_keys = sorted(keys, key=lambda item: (str(item[0]), item[1]))
    assert [operation[1:3] for operation in operations if operation[0] == "rebuild"] == expected_keys
    assert [operation[1] for operation in operations if operation[0] == "soldier_total"] == sorted(
        {soldier_id for soldier_id, _quarter in keys}, key=str
    )
    assert [operation[1] for operation in operations if operation[0] == "quarter_total"] == sorted(
        {quarter_start_value for _soldier_id, quarter_start_value in keys}
    )
    assert all(
        operation[3]
        == {"refresh_soldier_total": False, "refresh_quarter_total": False}
        for operation in operations
        if operation[0] == "rebuild"
    )
    assert result == {"checked": 2, "repaired": 2, "diverged": 0}


def test_bulk_refresh_waits_for_read_repair_bucket_marker(admin_engine, monkeypatch):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as setup_session:
        _seed_scoring_settings(setup_session)
        soldier = create_soldier(setup_session, personal_number="bulk-refresh-repair-marker-race")
        duty_type = _duty_type(setup_session, name="bulk-refresh-repair-marker-race-duty")
        location = _location(setup_session, name="bulk-refresh-repair-marker-race-location")
        assignment = create_assignment(
            setup_session,
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=date(2026, 7, 8),
            end_date=date(2026, 7, 10),
            is_reserve=True,
        )
        _complete_score_projection_backfill(setup_session)
        key = (soldier.id, date(2026, 7, 1))
        setup_session.commit()
        assignment_id = assignment.id
        soldier_id = soldier.id

    repair_bucket_computed = Event()
    allow_repair_to_commit = Event()
    bulk_marker_attempted = Event()
    bulk_partition_lock_attempted = Event()
    bulk_finished = Event()
    errors = []
    original_project = score_projection.project_soldier_bucket

    def pause_repair_after_projection(session, rebuilt_soldier_id, quarter_start_value):
        bucket = original_project(session, rebuilt_soldier_id, quarter_start_value)
        if current_thread().name == "score-projection-paused-repair":
            repair_bucket_computed.set()
            if not allow_repair_to_commit.wait(timeout=10):
                raise TimeoutError("test did not release the paused projection repair")
        return bucket

    def observe_bulk_lock_order(_connection, _cursor, statement, _parameters, _context, _executemany):
        if current_thread().name != "bulk-assignment-projection-writer":
            return
        normalized = statement.lower()
        if "insert into score_projection_dirty_buckets" in normalized:
            bulk_marker_attempted.set()
        if "from soldier_quarter_score_projection" in normalized and "for update" in normalized:
            bulk_partition_lock_attempted.set()

    monkeypatch.setattr(score_projection, "project_soldier_bucket", pause_repair_after_projection)

    def repair_bucket():
        try:
            with SessionLocal() as repair_session:
                score_projection._repair_projection_keys(repair_session, keys={key})
                repair_session.commit()
        except Exception as exc:
            errors.append(exc)

    def bulk_refresh_assignment():
        try:
            with SessionLocal() as writer_session:
                current_assignment = writer_session.get(DutyAssignment, assignment_id)
                current_assignment.called_up_from = date(2026, 7, 8)
                current_assignment.called_up_to = date(2026, 7, 8)
                writer_session.flush()
                refresh_projections_for_assignments_bulk(
                    writer_session, assignments=[current_assignment]
                )
                writer_session.commit()
        except Exception as exc:
            errors.append(exc)
        finally:
            bulk_finished.set()

    event.listen(admin_engine, "before_cursor_execute", observe_bulk_lock_order)
    repairer = Thread(target=repair_bucket, name="score-projection-paused-repair")
    bulk_writer = None
    repairer.start()
    try:
        assert repair_bucket_computed.wait(timeout=5), "repair did not compute the target bucket"
        bulk_writer = Thread(
            target=bulk_refresh_assignment, name="bulk-assignment-projection-writer"
        )
        bulk_writer.start()
        marker_attempted_before_repair_commit = bulk_marker_attempted.wait(timeout=2)
        if marker_attempted_before_repair_commit:
            partition_lock_before_repair_commit = bulk_partition_lock_attempted.wait(timeout=0.15)
            bulk_finished_before_repair_commit = bulk_finished.wait(timeout=0.15)
        else:
            # With the legacy bulk path, wait for its refresh to commit before
            # resuming the repair so the stale overwrite is deterministic.
            partition_lock_before_repair_commit = bulk_partition_lock_attempted.is_set()
            bulk_finished_before_repair_commit = bulk_finished.wait(timeout=5)
    finally:
        allow_repair_to_commit.set()
        repairer.join(timeout=10)
        if bulk_writer is not None:
            bulk_writer.join(timeout=10)
        event.remove(admin_engine, "before_cursor_execute", observe_bulk_lock_order)

    assert not repairer.is_alive()
    assert bulk_writer is not None and not bulk_writer.is_alive()
    assert bulk_finished.is_set()
    assert not errors
    with SessionLocal() as verify_session:
        assert _projection_summary(
            verify_session, soldier_id=soldier_id, quarter_start_value=key[1]
        )[0] == Decimal("3.000000")
        assert projection_is_current(verify_session, {key})
    assert marker_attempted_before_repair_commit
    assert not partition_lock_before_repair_commit
    assert not bulk_finished_before_repair_commit


def test_bulk_refresh_marker_sql_is_bounded_for_large_soldier_set(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    soldier_count = 64
    with SessionLocal() as session:
        _seed_scoring_settings(session)
        duty_type = _duty_type(session, name="bulk-marker-scale-duty")
        location = _location(session, name="bulk-marker-scale-location")
        soldiers = [
            create_soldier(session, personal_number=f"bulk-marker-scale-{index:03d}")
            for index in range(soldier_count)
        ]
        assignments = [
            DutyAssignment(
                soldier_id=soldier.id,
                duty_type_id=duty_type.id,
                duty_location_id=location.id,
                start_date=date(2026, 7, 8),
                end_date=date(2026, 7, 10),
                status="published",
            )
            for soldier in soldiers
        ]
        session.add_all(assignments)
        session.flush()

        marker_statements = []

        def count_marker_statements(_connection, _cursor, statement, _parameters, _context, _executemany):
            if "score_projection_dirty_buckets" in statement.lower():
                marker_statements.append(statement.lower())

        event.listen(admin_engine, "before_cursor_execute", count_marker_statements)
        try:
            refresh_projections_for_assignments_bulk(session, assignments=assignments)
        finally:
            event.remove(admin_engine, "before_cursor_execute", count_marker_statements)

        keys = {(soldier.id, date(2026, 7, 1)) for soldier in soldiers}
        assert projection_is_current(session, keys)
        marker_count = session.scalar(
            select(func.count()).select_from(ScoreProjectionDirtyBucket).where(
                ScoreProjectionDirtyBucket.soldier_id.in_([soldier.id for soldier in soldiers]),
                ScoreProjectionDirtyBucket.quarter_start == date(2026, 7, 1),
                ScoreProjectionDirtyBucket.status == "current",
            )
        )
        assert marker_count == soldier_count

    marker_upserts = [statement for statement in marker_statements if statement.lstrip().startswith("insert into")]
    marker_lock_reads = [
        statement
        for statement in marker_statements
        if statement.lstrip().startswith("select") and "for update" in statement
    ]
    marker_updates = [statement for statement in marker_statements if statement.lstrip().startswith("update")]
    assert len(marker_upserts) == 1
    assert len(marker_lock_reads) == 1
    assert len(marker_updates) == 1
    assert len(marker_statements) <= 4, (
        f"bulk refresh issued {len(marker_statements)} dirty-marker statements "
        f"for {soldier_count} soldiers"
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


def test_replace_assignment_refreshes_outgoing_soldier_projection(admin_session, admin_engine):
    """Regression for Finding 1: replace_assignment must dirty/refresh the
    OUTGOING soldier's projection bucket too, not just the replacement's --
    otherwise the outgoing soldier's cached quarter keeps counting a duty
    they no longer hold."""
    _seed_scoring_settings(admin_session)
    outgoing = create_soldier(admin_session, personal_number="fresh-replace-outgoing")
    replacement = create_soldier(admin_session, personal_number="fresh-replace-incoming")
    duty_type = _duty_type(admin_session, name="fresh-replace-duty")
    location = _location(admin_session, name="fresh-replace-location")
    target_quarter = date(2026, 7, 1)

    assignment = create_assignment(
        admin_session,
        soldier_id=outgoing.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )
    admin_session.commit()

    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=outgoing.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=outgoing.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)

    replace_assignment(
        admin_session, assignment=assignment, replacement_soldier_id=replacement.id,
    )
    admin_session.commit()

    # Both buckets must be persisted fresh -- the outgoing soldier's bucket
    # must no longer count this assignment, and the replacement's must.
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=outgoing.id, quarter_start_value=target_quarter
    )
    _assert_committed_bucket_is_fresh(
        admin_engine, soldier_id=replacement.id, quarter_start_value=target_quarter
    )
    assert _committed_projection_summary(
        admin_engine, soldier_id=outgoing.id, quarter_start_value=target_quarter
    ) == (Decimal("0.000000"), Decimal("0.000000"), 0)
    assert _committed_projection_summary(
        admin_engine, soldier_id=replacement.id, quarter_start_value=target_quarter
    ) == (Decimal("4.000000"), Decimal("0.000000"), 1)


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
