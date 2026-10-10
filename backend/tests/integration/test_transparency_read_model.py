"""PostgreSQL contracts for the versioned transparency read model."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import event, text

from app.services import transparency_read_model as model
from app.services.authority import SoldierScopeVisibility
from tests.helpers import create_node, create_soldier


def _visible(*, admin=False, commander=(), dm=(), every=False, threshold=None, best=None):
    return SoldierScopeVisibility(
        admin, frozenset(commander), frozenset(dm), every, threshold, best,
    )


def _generation(session, *, source=0, ready=True, as_of=None):
    identifier = uuid.uuid4()
    session.execute(text("""
        INSERT INTO transparency_read_model_generations
          (id, source_generation, source_snapshot, as_of, normalization_denominator, ready)
        VALUES (:id, :source, pg_current_snapshot()::text, :as_of, 1, :ready)
    """), {"id": identifier, "source": source, "as_of": as_of or date.today(), "ready": ready})
    session.commit()
    return identifier


def _row(session, generation, soldier, *, share, offset=0):
    session.execute(text("""
        INSERT INTO transparency_read_model_rows
          (generation_id, soldier_id, burden_share, cumulative_score, score_per_day,
           normalised_score, c_over_d, active_days, shift_count, burden_share_offset_raw,
           full_name, node_id, node_name, enrolled_at, rank, is_officer, service_type,
           is_globally_exempted)
        VALUES (:generation, :soldier, :share, 6, 3, 2, 1, 2, 1, :offset,
                :name, :node, :node_name, current_date, NULL, false, 'mandatory',
                false)
    """), {"generation": generation, "soldier": soldier.id, "share": share,
           "offset": offset, "name": soldier.full_name,
           "node": soldier.hierarchy_node_id, "node_name": None})


def test_schema_uses_numeric_uuid_keys_and_hides_incomplete_generation(admin_session):
    columns = admin_session.execute(text("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = 'transparency_read_model_rows'
    """)).all()
    types = dict(columns)
    assert types["burden_share"] == "numeric"
    assert types["soldier_id"] == "uuid"
    assert "payload" not in types
    incomplete = _generation(admin_session, ready=False)
    assert model.current_generation(admin_session, source_generation=0, as_of=date.today()) is None
    admin_session.execute(text("""
        UPDATE transparency_read_model_generations SET ready = true WHERE id = :id
    """), {"id": incomplete})
    admin_session.commit()
    assert model.current_generation(admin_session, source_generation=0, as_of=date.today())["id"] == incomplete
    assert model.current_generation(admin_session, source_generation=1, as_of=date.today()) is None
    assert model.current_generation(admin_session, source_generation=0, as_of=date(2000, 1, 1)) is None


def test_keyset_page_and_summary_apply_same_scope_and_self_rule(admin_session):
    admin = create_soldier(admin_session, personal_number="rm-admin", role="admin")
    root = create_node(admin_session, level="department", name="Root")
    child = create_node(admin_session, level="team", name="Child", parent=root)
    outside = create_node(admin_session, level="department", name="Outside")
    viewer = create_soldier(admin_session, personal_number="rm-viewer", hierarchy_node_id=outside.id)
    in_scope = create_soldier(admin_session, personal_number="rm-in", hierarchy_node_id=child.id)
    elsewhere = create_soldier(admin_session, personal_number="rm-out", hierarchy_node_id=outside.id)
    no_node = create_soldier(admin_session, personal_number="rm-none")
    generation = _generation(admin_session)
    for soldier, share, offset in (
        (admin, "9", 9), (viewer, "8", 8), (in_scope, "8", 7),
        (elsewhere, "8", 6), (no_node, "1", 1),
    ):
        _row(admin_session, generation, soldier, share=share, offset=offset)
    admin_session.commit()

    all_rows = model.read_page(
        admin_session, generation_id=generation, viewer=admin, visibility=_visible(admin=True),
        after_score=None, after_soldier_id=None, limit=10,
    )
    assert [row["soldier_id"] for row in all_rows] == [
        admin.id, *sorted([viewer.id, in_scope.id, elsewhere.id]), no_node.id,
    ]
    assert model.read_summary(
        admin_session, generation_id=generation, viewer=admin,
        visibility=_visible(admin=True),
    )["row_count"] == 5

    scope = _visible(commander=[root.id])
    scoped = model.read_page(
        admin_session, generation_id=generation, viewer=viewer, visibility=scope,
        after_score=None, after_soldier_id=None, limit=10,
    )
    assert {row["soldier_id"] for row in scoped} == {viewer.id, in_scope.id}
    assert model.read_summary(
        admin_session, generation_id=generation, viewer=viewer,
        visibility=scope,
    )["row_count"] == 2

    first = model.read_page(
        admin_session, generation_id=generation, viewer=admin, visibility=_visible(admin=True),
        after_score=None, after_soldier_id=None, limit=2,
    )
    second = model.read_page(
        admin_session, generation_id=generation, viewer=admin, visibility=_visible(admin=True),
        after_score=first[-1]["burden_share"],
        after_soldier_id=first[-1]["soldier_id"], limit=10,
    )
    assert [row["soldier_id"] for row in first + second] == [row["soldier_id"] for row in all_rows]
    assert isinstance(first[0]["burden_share"], Decimal)

    for visibility in (_visible(dm=[root.id]), _visible(every=True), _visible(threshold=3, best=2)):
        rows = model.read_page(
            admin_session, generation_id=generation, viewer=viewer, visibility=visibility,
            after_score=None, after_soldier_id=None, limit=10,
        )
        expected = 2 if visibility.dm_ancestor_ids else 5
        assert len(rows) == expected
        assert model.read_summary(
            admin_session, generation_id=generation, viewer=viewer,
            visibility=visibility,
        )["row_count"] == expected


def test_build_persists_batches_and_prunes_old_completed_generations(admin_session, monkeypatch):
    from app.services import scoring

    soldier = create_soldier(admin_session, personal_number="rm-build")
    canonical = scoring.transparency_rows(admin_session, viewer=None)
    assert canonical["rows"]
    monkeypatch.setattr(scoring, "_try_projected_transparency_rows", lambda session, *, viewer: canonical)

    def unexpected_second_scoring_call(session, *, viewer):
        raise AssertionError("builder must use the projected result directly")

    monkeypatch.setattr(scoring, "transparency_rows", unexpected_second_scoring_call)
    old = _generation(admin_session, source=-2)
    previous = _generation(admin_session, source=-1)
    built = model.rebuild_generation(admin_session)
    assert built is not None
    assert built["ready"] is True
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_rows WHERE generation_id = :id
    """), {"id": built["id"]}).scalar_one() == len(canonical["rows"])
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_generations WHERE ready
    """)).scalar_one() == 2
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_generations WHERE id IN (:old, :previous)
    """), {"old": old, "previous": previous}).scalar_one() == 1
    assert soldier.id in {row["soldier_id"] for row in model.read_page(
        admin_session, generation_id=built["id"], viewer=soldier,
        visibility=_visible(), after_score=None,
        after_soldier_id=None, limit=10,
    )}


def test_build_aborts_when_source_generation_changes(admin_session, monkeypatch):
    from app.services import scoring

    create_soldier(admin_session, personal_number="rm-race")
    canonical = scoring.transparency_rows(admin_session, viewer=None)

    def changed_during_projected_read(session, *, viewer):
        session.execute(text("SELECT nextval('transparency_source_generation_seq')"))
        return canonical

    monkeypatch.setattr(scoring, "_try_projected_transparency_rows", changed_during_projected_read)
    assert model.rebuild_generation(admin_session) is None
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_generations WHERE ready
    """)).scalar_one() == 0


def test_build_aborts_when_journal_commit_was_invisible_at_capture(
    admin_session, admin_engine, monkeypatch,
):
    from app.services import scoring

    create_soldier(admin_session, personal_number="rm-journal-race")
    canonical = scoring.transparency_rows(admin_session, viewer=None)
    def commit_journal_during_projected_read(session, *, viewer):
        with admin_engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO transparency_source_change_journal (transaction_id)
                VALUES (pg_current_xact_id())
            """))
        return canonical

    monkeypatch.setattr(scoring, "_try_projected_transparency_rows", commit_journal_during_projected_read)
    assert model.rebuild_generation(admin_session) is None
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_generations WHERE ready
    """)).scalar_one() == 0


def test_build_persists_rows_in_bounded_batches(admin_session, admin_engine, monkeypatch):
    from app.services import scoring

    soldier = create_soldier(admin_session, personal_number="rm-batch")
    base = scoring.transparency_rows(admin_session, viewer=None)["rows"][0]
    rows = [{**base, "soldier_id": uuid.uuid4()} for _ in range(5)]
    canonical = {"rows": rows, "population_count": len(rows)}
    monkeypatch.setattr(scoring, "_try_projected_transparency_rows", lambda session, *, viewer: canonical)
    monkeypatch.setattr(model, "_BATCH_SIZE", 2)
    inserts = []

    def observe_insert(connection, cursor, statement, parameters, context, executemany):
        if "INSERT INTO transparency_read_model_rows" in statement:
            inserts.append(statement)

    event.listen(admin_engine, "before_cursor_execute", observe_insert)
    try:
        generation = model.rebuild_generation(admin_session)
    finally:
        event.remove(admin_engine, "before_cursor_execute", observe_insert)
    assert generation is not None
    assert len(inserts) == 3
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_rows WHERE generation_id = :id
    """), {"id": generation["id"]}).scalar_one() == 5
    assert soldier.id not in {row["soldier_id"] for row in rows}


def test_build_with_incomplete_projections_publishes_nothing(admin_session):
    create_soldier(admin_session, personal_number="rm-unready")
    assert model.rebuild_generation(admin_session) is None
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_generations WHERE ready
    """)).scalar_one() == 0


def test_journal_detects_commit_invisible_at_capture(admin_session, admin_engine):
    source, snapshot = model.capture_source_state(admin_session)
    generation = _generation(admin_session, source=source)
    assert model.current_generation(
        admin_session, source_generation=source, as_of=date.today(),
    )["id"] == generation
    with admin_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO transparency_source_change_journal (transaction_id)
            VALUES (pg_current_xact_id())
        """))
    assert model.source_changed_since_snapshot(admin_session, snapshot) is True
    assert model.current_generation(
        admin_session, source_generation=source, as_of=date.today(),
    ) is None


def test_summary_empty_and_single_row_null_rules(admin_session):
    admin = create_soldier(admin_session, personal_number="rm-summary", role="admin")
    generation = _generation(admin_session)
    empty = model.read_summary(
        admin_session, generation_id=generation, viewer=admin,
        visibility=_visible(admin=True),
    )
    assert empty["row_count"] == 0
    assert empty["average_active_days"] == 0
    assert empty["burden_share_mean"] is None
    assert empty["burden_share_offset_min"] is None
    _row(admin_session, generation, admin, share="1.25", offset=7)
    admin_session.commit()
    one = model.read_summary(
        admin_session, generation_id=generation, viewer=admin,
        visibility=_visible(admin=True),
    )
    assert one["row_count"] == 1
    assert one["burden_share_mean"] is None
    assert one["burden_share_stddev"] is None
    assert one["burden_share_offset_min"] == 7


def test_worker_tick_publishes_generation_then_reuses_it(admin_session, monkeypatch):
    from types import SimpleNamespace

    from app import transparency_read_model_worker as worker
    from app.services import scoring

    monkeypatch.setattr(
        worker, "get_settings",
        lambda: SimpleNamespace(transparency_read_model_enabled=True),
    )

    create_soldier(admin_session, personal_number="rm-worker")
    canonical = scoring.transparency_rows(admin_session, viewer=None)
    monkeypatch.setattr(
        scoring, "_try_projected_transparency_rows",
        lambda session, *, viewer: canonical,
    )

    assert worker._refresh_tick() is True
    source_generation, _snapshot = model.capture_source_state(admin_session)
    published = model.current_generation(
        admin_session, source_generation=source_generation, as_of=date.today(),
    )
    assert published is not None
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_rows WHERE generation_id = :id
    """), {"id": published["id"]}).scalar_one() == len(canonical["rows"])

    assert worker._refresh_tick() is True
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_read_model_generations WHERE ready
    """)).scalar_one() == 1


def test_overlapping_worker_tick_cannot_duplicate_build_after_builder_commit(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from app import transparency_read_model_worker as worker

    monkeypatch.setattr(
        worker, "get_settings",
        lambda: SimpleNamespace(transparency_read_model_enabled=True),
    )

    started = threading.Event()
    finish = threading.Event()
    builds: list[str] = []
    monkeypatch.setattr(worker.model, "capture_source_state", lambda session: (23, "snapshot"))
    monkeypatch.setattr(worker.model, "current_generation", lambda *args, **kwargs: None)

    def commit_then_pause(session):
        # Task 1's real builder commits before returning. Its transaction must
        # not release the advisory lock that protects this whole refresh tick.
        session.execute(text("SELECT 1"))
        session.commit()
        builds.append("started")
        started.set()
        assert finish.wait(timeout=10)
        return {"id": "generation-23", "source_generation": 23}

    monkeypatch.setattr(worker.model, "rebuild_generation", commit_then_pause)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(worker._refresh_tick)
        assert started.wait(timeout=10)
        second = worker._refresh_tick()
        finish.set()
        assert first.result(timeout=10) is True

    assert second is False
    assert builds == ["started"]
