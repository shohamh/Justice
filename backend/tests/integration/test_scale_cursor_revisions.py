from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from threading import Event, Thread

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    DutyManagerScope,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    SoldierExemption,
    SystemSetting,
)
from tests.helpers import auth_headers, create_node, create_soldier


def _revision(session, table: str) -> int:
    return session.execute(text(f"SELECT revision FROM {table} WHERE singleton = TRUE")).scalar_one()


def _source_generation(session) -> int:
    return session.execute(
        text(
            "SELECT CASE WHEN is_called THEN last_value ELSE 0 END "
            "FROM transparency_source_generation_seq"
        )
    ).scalar_one()


_TRANSPARENCY_SOURCE_TABLES = {
    "soldiers",
    "duty_assignments",
    "duty_day_overrides",
    "duty_dismissals",
    "score_adjustments",
    "duty_types",
    "soldier_exemptions",
    "exemption_types",
    "exemption_duty_type_map",
    "hierarchy_nodes",
    "hierarchy_level_types",
    "duty_manager_scope",
    "role_deputies",
    "system_settings",
}


def _transparency_row(soldier_id: uuid.UUID, full_name: str, *, node_id=None, node_name=None) -> dict:
    return {
        "soldier_id": soldier_id,
        "full_name": full_name,
        "node_id": node_id,
        "node_name": node_name,
        "enrolled_at": date(2020, 1, 1),
        "active_days": 10,
        "shift_count": 1,
        "rank": None,
        "is_officer": False,
        "service_type": None,
        "cumulative_score": Decimal("2.00"),
        "score_per_day": Decimal("0.20"),
        "normalised_score": Decimal("1.00"),
        "is_globally_exempted": False,
        "burden_share": 0.5,
        "c_over_d": 1.0,
        "burden_share_offset_raw": 0,
        "exemptions_display": "",
        "exemptions_visible": False,
        "exemptions": [],
        "has_global_exemption": None,
        "has_partial_exemption": None,
        "has_temporary_exemption": None,
    }


def test_transparency_source_generation_has_dml_and_truncate_triggers_on_canonical_inputs(
    admin_session,
):
    triggers = admin_session.execute(
        text(
            """
            SELECT c.relname, t.tgname
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            WHERE NOT t.tgisinternal
              AND t.tgname LIKE '%_transparency_source_%'
            """
        )
    ).all()
    dml_tables = {
        table for table, name in triggers if name.endswith("_transparency_source_dml")
    }
    truncate_tables = {
        table for table, name in triggers if name.endswith("_transparency_source_truncate")
    }

    assert dml_tables == _TRANSPARENCY_SOURCE_TABLES
    assert truncate_tables == _TRANSPARENCY_SOURCE_TABLES
    assert not {
        "soldier_score_projection",
        "soldier_quarter_score_projection",
        "score_projection_dirty_buckets",
        "score_projection_divergent_buckets",
        "score_projection_state",
    }.intersection(dml_tables | truncate_tables)


def test_transparency_source_generation_bumps_once_for_multrow_dml(admin_session):
    for index in range(3):
        create_soldier(admin_session, personal_number=f"cursor-source-multi-{index}")
    admin_session.commit()

    generation = _source_generation(admin_session)
    admin_session.execute(
        text(
            "UPDATE soldiers SET full_name = full_name "
            "WHERE personal_number LIKE 'cursor-source-multi-%'"
        )
    )

    assert _source_generation(admin_session) == generation + 1


def test_transparency_source_generation_advances_on_truncate(admin_session):
    generation = _source_generation(admin_session)

    admin_session.execute(text("TRUNCATE TABLE hierarchy_level_types"))

    assert _source_generation(admin_session) == generation + 1


def test_transparency_source_generation_advances_even_when_source_change_rolls_back(
    admin_session,
):
    soldier = create_soldier(admin_session, personal_number="cursor-source-rollback")
    admin_session.commit()
    generation = _source_generation(admin_session)

    admin_session.execute(
        text("UPDATE soldiers SET full_name = 'Rolled Back Name' WHERE id = :id"),
        {"id": soldier.id},
    )
    admin_session.rollback()

    assert _source_generation(admin_session) == generation + 1
    assert admin_session.execute(
        text("SELECT full_name FROM soldiers WHERE id = :id"), {"id": soldier.id}
    ).scalar_one() == soldier.full_name


def test_transparency_page_cursor_rejects_direct_sql_name_change(client, admin_session, monkeypatch):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="cursor-source-admin", role="admin")
    first_soldier = create_soldier(admin_session, personal_number="cursor-source-first")
    second_soldier = create_soldier(admin_session, personal_number="cursor-source-second")
    admin_session.commit()

    rows = [
        _transparency_row(first_soldier.id, first_soldier.full_name),
        _transparency_row(second_soldier.id, second_soldier.full_name),
    ]
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(item) for item in rows],
            "can_see_exemption_aggregates": True,
        },
    )

    first_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1},
        headers=auth_headers(admin),
    )
    assert first_page.status_code == 200
    cursor = first_page.json()["next_cursor"]
    assert cursor

    admin_session.execute(
        text("UPDATE soldiers SET full_name = 'Renamed by direct SQL' WHERE id = :id"),
        {"id": second_soldier.id},
    )
    admin_session.commit()

    second_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "cursor": cursor},
        headers=auth_headers(admin),
    )
    assert second_page.status_code == 409
    assert second_page.json()["detail"] == "stale_cursor"


def test_transparency_cursor_rejects_source_transaction_committed_after_page_one(
    client, admin_engine, admin_session, monkeypatch
):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="cursor-source-commit-admin", role="admin")
    target = create_soldier(admin_session, personal_number="cursor-source-commit-target")
    admin_session.commit()
    rows = [
        _transparency_row(target.id, target.full_name),
        _transparency_row(admin.id, admin.full_name),
    ]
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(item) for item in rows],
            "can_see_exemption_aggregates": True,
        },
    )

    source_write_ready = Event()
    allow_source_commit = Event()
    writer_errors: list[Exception] = []
    writer_xids: list[str] = []
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)

    def write_and_hold_transaction():
        try:
            with SessionLocal() as writer_session:
                writer_xids.append(
                    writer_session.execute(text("SELECT pg_current_xact_id()::text")).scalar_one()
                )
                writer_session.execute(
                    text("UPDATE soldiers SET full_name = 'Committed After Page One' WHERE id = :id"),
                    {"id": target.id},
                )
                source_write_ready.set()
                if not allow_source_commit.wait(timeout=10):
                    raise TimeoutError("page-one request did not release the source writer")
                writer_session.commit()
        except Exception as exc:
            writer_errors.append(exc)
            source_write_ready.set()

    writer = Thread(target=write_and_hold_transaction)
    writer.start()
    first_page = None
    try:
        assert source_write_ready.wait(timeout=5), "source writer did not reach its uncommitted update"
        first_page = client.get(
            "/api/scoring/transparency/page",
            params={"page_size": 1},
            headers=auth_headers(admin),
        )
        assert first_page.status_code == 200
        assert first_page.json()["next_cursor"]
        cursor_payload = scoring_route.jwt.decode(
            first_page.json()["next_cursor"],
            scoring_route.get_settings().jwt_secret,
            algorithms=[scoring_route.get_settings().jwt_algorithm],
        )
        captured_snapshot = cursor_payload["source_snapshot"]
    finally:
        allow_source_commit.set()
        writer.join(timeout=10)

    assert not writer.is_alive()
    assert not writer_errors
    assert first_page is not None
    assert len(writer_xids) == 1
    with SessionLocal() as diagnostic_session:
        committed_journal_xid = diagnostic_session.execute(
            text(
                "SELECT transaction_id::text FROM transparency_source_change_journal "
                "WHERE transaction_id = CAST(:xid AS xid8)"
            ),
            {"xid": writer_xids[0]},
        ).scalar_one_or_none()
        is_invisible_to_captured_snapshot = diagnostic_session.execute(
            text(
                "SELECT NOT pg_visible_in_snapshot(CAST(:xid AS xid8), "
                "CAST(:snapshot AS pg_snapshot))"
            ),
            {"xid": writer_xids[0], "snapshot": captured_snapshot},
        ).scalar_one()
        assert scoring_route._transparency_source_changed_since_snapshot(
            diagnostic_session, captured_snapshot
        )
    assert committed_journal_xid == writer_xids[0]
    assert is_invisible_to_captured_snapshot
    from app.services import transparency_page_store

    with SessionLocal() as cleanup_session:
        transparency_page_store.cleanup_expired(cleanup_session)
        cleanup_session.commit()
        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_source_change_journal
            WHERE transaction_id = CAST(:xid AS xid8)
        """), {"xid": writer_xids[0]}).scalar_one() == 1
    second_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "cursor": first_page.json()["next_cursor"]},
        headers=auth_headers(admin),
    )

    assert second_page.status_code == 409
    assert second_page.json()["detail"] == "stale_cursor"


def test_transparency_journal_cleanup_retains_event_for_live_snapshot(client, admin_session, monkeypatch):
    from app.routes import scoring as scoring_route
    from app.services import transparency_page_store

    admin = create_soldier(admin_session, personal_number="journal-retention-admin", role="admin")
    target = create_soldier(admin_session, personal_number="journal-retention-target")
    admin_session.commit()
    rows = [
        _transparency_row(admin.id, admin.full_name),
        _transparency_row(target.id, target.full_name),
    ]
    monkeypatch.setattr(scoring_route.svc, "transparency_rows", lambda session, *, viewer: {
        "rows": [dict(row) for row in rows],
        "can_see_exemption_aggregates": True,
    })
    first = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1},
        headers=auth_headers(admin),
    )
    assert first.status_code == 200
    payload = scoring_route.jwt.decode(
        first.json()["next_cursor"], scoring_route.get_settings().jwt_secret,
        algorithms=[scoring_route.get_settings().jwt_algorithm],
    )
    snapshot_id = payload["snapshot_id"]
    captured = payload["source_snapshot"]

    admin_session.execute(text("UPDATE soldiers SET full_name = 'After Capture' WHERE id = :id"), {"id": target.id})
    writer_xid = admin_session.execute(text("SELECT pg_current_xact_id()::text")).scalar_one()
    admin_session.commit()
    assert admin_session.execute(text("""
        SELECT NOT pg_visible_in_snapshot(CAST(:xid AS xid8), CAST(:snapshot AS pg_snapshot))
    """), {"xid": writer_xid, "snapshot": captured}).scalar_one()

    transparency_page_store.cleanup_expired(admin_session)
    admin_session.commit()
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_source_change_journal
        WHERE transaction_id = CAST(:xid AS xid8)
    """), {"xid": writer_xid}).scalar_one() == 1

    admin_session.execute(text("""
        UPDATE transparency_page_snapshots SET expires_at = now() - interval '1 second'
        WHERE id = :id
    """), {"id": snapshot_id})
    admin_session.commit()
    transparency_page_store.cleanup_expired(admin_session)
    admin_session.commit()
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_source_change_journal
        WHERE transaction_id = CAST(:xid AS xid8)
    """), {"xid": writer_xid}).scalar_one() == 0
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_page_snapshots WHERE id = :id
    """), {"id": snapshot_id}).scalar_one() == 0


def test_transparency_persisted_cursor_is_bound_to_user_filters_and_page_size(
    client, admin_session, monkeypatch,
):
    from app.routes import scoring as scoring_route

    first_admin = create_soldier(admin_session, personal_number="snapshot-binding-first", role="admin")
    other_admin = create_soldier(admin_session, personal_number="snapshot-binding-other", role="admin")
    rows = [
        _transparency_row(first_admin.id, first_admin.full_name),
        _transparency_row(other_admin.id, other_admin.full_name),
    ]
    monkeypatch.setattr(scoring_route.svc, "transparency_rows", lambda session, *, viewer: {
        "rows": [dict(row) for row in rows],
        "can_see_exemption_aggregates": True,
    })
    first = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1},
        headers=auth_headers(first_admin),
    )
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor

    for headers, extra in (
        (auth_headers(other_admin), {}),
        (auth_headers(first_admin), {"search": "other"}),
        (auth_headers(first_admin), {"sort": "name"}),
        (auth_headers(first_admin), {"page_size": 2}),
        (auth_headers(first_admin), {"rank_order": "A"}),
    ):
        response = client.get(
            "/api/scoring/transparency/page",
            params={"page_size": 1, "cursor": cursor, **extra}, headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_cursor"


def test_failed_transparency_build_discards_registered_snapshot(client, admin_session, monkeypatch):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="failed-snapshot-admin", role="admin")
    admin_session.commit()
    monkeypatch.setattr(scoring_route.svc, "transparency_rows", lambda session, *, viewer: {
        "rows": [_transparency_row(admin.id, admin.full_name)],
        "can_see_exemption_aggregates": True,
    })

    def fail_fairness(session, *, viewer, node_id):
        raise RuntimeError("fairness assembly failed")

    monkeypatch.setattr(scoring_route.svc, "fairness_components", fail_fairness)
    response = client.get(
        "/api/scoring/transparency/page", params={"group_key": "comp_0"},
        headers=auth_headers(admin),
    )
    assert response.status_code == 500
    assert admin_session.execute(text("""
        SELECT count(*) FROM transparency_page_snapshots WHERE ready = false
    """)).scalar_one() == 0


def test_persisted_fairness_group_sort_and_summary_use_canonical_grouping(
    client, admin_session, monkeypatch,
):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="snapshot-fairness-admin", role="admin")
    a = create_soldier(admin_session, personal_number="snapshot-fairness-a")
    b = create_soldier(admin_session, personal_number="snapshot-fairness-b")
    c = create_soldier(admin_session, personal_number="snapshot-fairness-c")
    admin_session.commit()
    source_rows = [
        _transparency_row(b.id, "B"),
        _transparency_row(c.id, "C"),
        _transparency_row(a.id, "A"),
    ]
    for row, share in zip(source_rows, (0.3, 0.2, 0.1), strict=True):
        row["burden_share"] = share
    monkeypatch.setattr(scoring_route.svc, "transparency_rows", lambda session, *, viewer: {
        "rows": [dict(row) for row in source_rows],
        "can_see_exemption_aggregates": True,
    })
    calls = 0

    def fairness(session, *, viewer, node_id):
        nonlocal calls
        calls += 1
        return {
            "components": [{
                "burden_share": {"mean": 0.2},
                "soldiers": [
                    {"soldier_id": str(b.id), "burden_share": 0.3},
                    {"soldier_id": str(a.id), "burden_share": 0.1},
                ],
            }],
            "exempt_from_all": {"soldiers": []},
        }

    monkeypatch.setattr(scoring_route.svc, "fairness_components", fairness)
    ordinary = client.get(
        "/api/scoring/transparency/page", params={"sort": "name"},
        headers=auth_headers(admin),
    )
    assert ordinary.status_code == 200
    assert calls == 0

    params = {"group_key": "comp_0", "sort": "group_dev", "page_size": 1}
    first = client.get("/api/scoring/transparency/page", params=params, headers=auth_headers(admin))
    assert first.status_code == 200
    assert first.json()["summary"]["row_count"] == 2
    assert (first.json()["items"][0]["soldier_id"], first.json()["items"][0]["row_num"]) == (str(b.id), 1)
    assert calls == 1

    monkeypatch.setattr(scoring_route.svc, "fairness_components", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fairness recomputed")))
    second = client.get(
        "/api/scoring/transparency/page",
        params={**params, "cursor": first.json()["next_cursor"]},
        headers=auth_headers(admin),
    )
    assert second.status_code == 200
    assert (second.json()["items"][0]["soldier_id"], second.json()["items"][0]["row_num"]) == (str(a.id), 2)


def test_transparency_page_rejects_concurrent_source_change_during_fairness_assembly(
    client, admin_engine, admin_session, monkeypatch
):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="cursor-source-race-admin", role="admin")
    target = create_soldier(admin_session, personal_number="cursor-source-race-target")
    admin_session.commit()
    row = _transparency_row(target.id, target.full_name)
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(row)],
            "can_see_exemption_aggregates": True,
        },
    )

    source_snapshot = scoring_route._transparency_source_snapshot
    captured_snapshots: list[str] = []

    def capture_source_snapshot(session):
        snapshot = source_snapshot(session)
        captured_snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(scoring_route, "_transparency_source_snapshot", capture_source_snapshot)

    mutation_finished = Event()
    mutation_errors: list[Exception] = []
    writer_xids: list[str] = []
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)

    def mutate_source_from_independent_session():
        try:
            with SessionLocal() as writer_session:
                writer_xids.append(
                    writer_session.execute(text("SELECT pg_current_xact_id()::text")).scalar_one()
                )
                writer_session.execute(
                    text("UPDATE soldiers SET full_name = 'Concurrent Rename' WHERE id = :id"),
                    {"id": target.id},
                )
                writer_session.commit()
        except Exception as exc:  # surfaced on the request thread below
            mutation_errors.append(exc)
        finally:
            mutation_finished.set()

    def mutate_during_fairness(session, *, viewer, node_id):
        writer = Thread(target=mutate_source_from_independent_session)
        writer.start()
        assert mutation_finished.wait(timeout=5), "independent source writer did not finish"
        writer.join(timeout=5)
        assert not writer.is_alive()
        assert not mutation_errors
        return {
            "components": [{"soldiers": [{"soldier_id": str(target.id)}]}],
            "exempt_from_all": {"soldiers": []},
        }

    monkeypatch.setattr(scoring_route.svc, "fairness_components", mutate_during_fairness)

    response = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "data_changed"
    assert len(captured_snapshots) == 1
    assert len(writer_xids) == 1
    with SessionLocal() as diagnostic_session:
        assert diagnostic_session.execute(
            text(
                "SELECT NOT pg_visible_in_snapshot(CAST(:xid AS xid8), "
                "CAST(:snapshot AS pg_snapshot))"
            ),
            {"xid": writer_xids[0], "snapshot": captured_snapshots[0]},
        ).scalar_one()
        assert scoring_route._transparency_source_changed_since_snapshot(
            diagnostic_session, captured_snapshots[0]
        )


def test_roster_revision_tracks_all_roster_tree_and_hakpaza_fields(admin_session):
    manager = create_soldier(admin_session, personal_number="cursor-rev-dm", role="soldier")
    commander = create_soldier(admin_session, personal_number="cursor-rev-cmd")
    parent = create_node(admin_session, level="department", name="cursor-rev-parent")
    node = create_node(admin_session, level="team", name="cursor-rev-node")
    duty_type = DutyType(name="cursor-rev-duty", score_per_day=Decimal("1"))
    admin_session.add(duty_type)
    admin_session.commit()

    revision = _revision(admin_session, "soldier_roster_revision")

    admin_session.execute(
        text("UPDATE soldiers SET rank = 'captain' WHERE id = :id"), {"id": manager.id}
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE hierarchy_nodes SET level = 'branch' WHERE id = :id"), {"id": node.id}
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE hierarchy_nodes SET commander_id = :commander WHERE id = :id"),
        {"id": node.id, "commander": commander.id},
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE hierarchy_nodes SET parent_id = :parent WHERE id = :id"),
        {"id": node.id, "parent": parent.id},
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.add(DutyManagerScope(duty_manager_id=manager.id, hierarchy_node_id=node.id))
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE duty_types SET name = 'cursor-rev-duty-renamed' WHERE id = :id"),
        {"id": duty_type.id},
    )
    admin_session.flush()
    assert _revision(admin_session, "soldier_roster_revision") == revision + 1


def test_transparency_page_cursor_rejects_fairness_membership_change(
    client, admin_session, monkeypatch
):
    from app.routes import scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="cursor-rev-admin", role="admin")
    first_soldier = create_soldier(admin_session, personal_number="cursor-rev-first")
    second_soldier = create_soldier(admin_session, personal_number="cursor-rev-second")
    first_id = first_soldier.id
    second_id = second_soldier.id
    duty_type = DutyType(name="cursor-rev-fairness-duty", score_per_day=Decimal("1"))
    exemption_type = ExemptionType(name="cursor-rev-fairness-exemption")
    admin_session.add_all([duty_type, exemption_type])
    admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=second_id,
            exemption_type_id=exemption_type.id,
            start_date=date.today(),
        )
    )
    admin_session.commit()

    def row(soldier_id: uuid.UUID, name: str, burden_share: float) -> dict:
        return {
            "soldier_id": soldier_id,
            "full_name": name,
            "node_id": None,
            "node_name": None,
            "enrolled_at": date(2020, 1, 1),
            "active_days": 10,
            "shift_count": 1,
            "rank": None,
            "is_officer": False,
            "service_type": None,
            "cumulative_score": Decimal("2.00"),
            "score_per_day": Decimal("0.20"),
            "normalised_score": Decimal("1.00"),
            "is_globally_exempted": False,
            "burden_share": burden_share,
            "c_over_d": 1.0,
            "burden_share_offset_raw": 0,
            "exemptions_display": "",
            "exemptions_visible": False,
            "exemptions": [],
            "has_global_exemption": None,
            "has_partial_exemption": None,
            "has_temporary_exemption": None,
        }

    source_rows = [row(first_id, "First", 0.9), row(second_id, "Second", 0.2)]
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(item) for item in source_rows],
            "can_see_exemption_aggregates": True,
        },
    )
    def fairness_components(session, *, viewer, node_id):
        mapping_exists = (
            session.query(ExemptionDutyTypeMap)
            .filter_by(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
            .count()
            > 0
        )
        members = [str(first_id)] if mapping_exists else [str(first_id), str(second_id)]
        exempt = [str(second_id)] if mapping_exists else []
        return {
            "components": [{"soldiers": [{"soldier_id": soldier_id} for soldier_id in members]}],
            "exempt_from_all": {"soldiers": [{"soldier_id": soldier_id} for soldier_id in exempt]},
        }

    monkeypatch.setattr(scoring_route.svc, "fairness_components", fairness_components)

    first_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0"},
        headers=auth_headers(admin),
    )
    assert first_page.status_code == 200
    cursor = first_page.json()["next_cursor"]
    assert cursor

    admin_session.add(
        ExemptionDutyTypeMap(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
    )
    admin_session.commit()

    second_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0", "cursor": cursor},
        headers=auth_headers(admin),
    )
    assert second_page.status_code == 409
    assert second_page.json()["detail"] == "stale_cursor"


def test_transparency_page_rejects_scope_change_during_page_assembly(
    client, admin_session, monkeypatch
):
    from app.routes import scoring as scoring_route

    node = create_node(admin_session, level="department", name="cursor-race-scoped")
    added_node = create_node(admin_session, level="department", name="cursor-race-added")
    manager = create_soldier(
        admin_session,
        personal_number="cursor-race-manager",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    target = create_soldier(admin_session, personal_number="cursor-race-target")
    source_row = {
        "soldier_id": target.id,
        "full_name": "Target",
        "node_id": node.id,
        "node_name": node.name,
        "enrolled_at": date(2020, 1, 1),
        "active_days": 10,
        "shift_count": 1,
        "rank": None,
        "is_officer": False,
        "service_type": None,
        "cumulative_score": Decimal("2.00"),
        "score_per_day": Decimal("0.20"),
        "normalised_score": Decimal("1.00"),
        "is_globally_exempted": False,
        "burden_share": 0.5,
        "c_over_d": 1.0,
        "burden_share_offset_raw": 0,
        "exemptions_display": "",
        "exemptions_visible": False,
        "exemptions": [],
        "has_global_exemption": None,
        "has_partial_exemption": None,
        "has_temporary_exemption": None,
    }
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda session, *, viewer: {
            "rows": [dict(source_row)],
            "can_see_exemption_aggregates": True,
        },
    )

    def mutate_scope_during_grouping(session, *, viewer, node_id):
        session.add(
            DutyManagerScope(duty_manager_id=manager.id, hierarchy_node_id=added_node.id)
        )
        session.flush()
        return {
            "components": [{"soldiers": [{"soldier_id": str(target.id)}]}],
            "exempt_from_all": {"soldiers": []},
        }

    monkeypatch.setattr(scoring_route.svc, "fairness_components", mutate_scope_during_grouping)

    response = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "group_key": "comp_0"},
        headers=auth_headers(manager),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "data_changed"


def test_transparency_source_generation_tracks_eligibility_and_scope_mutations(admin_session):
    soldier = create_soldier(admin_session, personal_number="cursor-rev-eligibility")
    duty_type = DutyType(name="cursor-rev-eligibility-duty", score_per_day=Decimal("1"))
    exemption_type = ExemptionType(name="cursor-rev-eligibility-exemption")
    admin_session.add_all([duty_type, exemption_type])
    admin_session.commit()

    revision = _source_generation(admin_session)

    duty_type.active = False
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    duty_type.requirements = {"allowed_genders": ["female"]}
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    exemption_type.is_global = True
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    admin_session.add(
        ExemptionDutyTypeMap(exemption_type_id=exemption_type.id, duty_type_id=duty_type.id)
    )
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    admin_session.execute(
        text("UPDATE soldiers SET gender = 'female' WHERE id = :id"), {"id": soldier.id}
    )
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    today = date.today()
    admin_session.add(
        SoldierExemption(
            soldier_id=soldier.id,
            exemption_type_id=exemption_type.id,
            start_date=today,
            end_date=today,
        )
    )
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    exemption = admin_session.query(SoldierExemption).filter_by(soldier_id=soldier.id).one()
    exemption.end_date = date.fromordinal(today.toordinal() + 1)
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    setting = admin_session.get(SystemSetting, "eligibility.mitvahim_months")
    if setting is None:
        admin_session.add(SystemSetting(key="eligibility.mitvahim_months", value=7))
    else:
        setting.value = 7
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    scope_setting = admin_session.get(SystemSetting, "transparency.min_visible_level")
    if scope_setting is None:
        admin_session.add(SystemSetting(key="transparency.min_visible_level", value="every_soldier"))
    else:
        scope_setting.value = "every_soldier"
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    root_a = create_node(admin_session, level="department", name="cursor-rev-root-a")
    root_b = create_node(admin_session, level="department", name="cursor-rev-root-b")
    child = create_node(
        admin_session, level="team", name="cursor-rev-child", parent=root_a
    )
    revision = _source_generation(admin_session)
    child.parent_id = root_b.id
    child.path_ids = [root_b.id, child.id]
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    child.level = "branch"
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    child.commander_id = soldier.id
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    child.parent_id = root_a.id
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    soldier.hierarchy_node_id = child.id
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    scope_manager = create_soldier(admin_session, personal_number="cursor-rev-scope-manager")
    revision = _source_generation(admin_session)
    scope = DutyManagerScope(duty_manager_id=scope_manager.id, hierarchy_node_id=root_a.id)
    admin_session.add(scope)
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    scope.hierarchy_node_id = root_b.id
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
    revision += 1

    admin_session.delete(scope)
    admin_session.flush()
    assert _source_generation(admin_session) == revision + 1
