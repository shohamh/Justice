"""Backfill test for migration 4a4997526f58 (unify swap requests with candidates).

Runs the migration's backfill logic against a throwaway Postgres container of
its own, independent of the shared session-scoped container in conftest.py:
that container is already migrated straight to head before any test runs, so
there's no way to seed pre-migration rows against it. This test instead
upgrades a fresh container to the migration's own down_revision, seeds rows
in the OLD two-party swap_requests schema, upgrades one more step to the
migration under test, and asserts on the resulting swap_requests /
swap_candidates / swap_manager_approvals rows.

Covers the fix for the gap where a pre-existing `pending_approval` row and a
separate `open` row for the same (requesting_soldier_id, duty_assignment_id)
were NOT consolidated by the original backfill (only same-status rows were
grouped), so both would end up status='open' after migration -- violating
the new partial unique index `uq_swap_requests_one_open_per_requester_duty`
and, worse, resurrecting the exact two-live-open-parents state this whole
migration exists to eliminate.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "990fbafee861"
REVISION = "4a4997526f58"


def test_pending_approval_and_open_row_same_requester_duty_consolidate():
    """Seed one pending_approval row and one open row for the same
    (requester, duty) pre-migration; assert the backfill merges them into a
    single surviving open parent instead of leaving two open rows.
    """
    # Save/restore process-global state this test has to mutate: the app
    # settings singleton is lru_cache'd (app/settings.py:get_settings), and
    # alembic/env.py always resolves its DB url from it, so pointing alembic
    # at a private throwaway container -- instead of the shared session
    # container conftest.py already migrated to head -- means temporarily
    # repointing DATABASE_URL/DB_ADMIN_URL and clearing that cache. Restored
    # in `finally` so later tests in this worker process see the original
    # (shared container) settings again.
    from app.settings import get_settings

    saved_database_url = os.environ.get("DATABASE_URL")
    saved_db_admin_url = os.environ.get("DB_ADMIN_URL")

    with PostgresContainer(
        "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="justice"
    ).with_command(
        "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
    ) as pg:
        url = make_url(pg.get_connection_url()).set(drivername="postgresql+psycopg")
        db_url = url.render_as_string(hide_password=False)

        try:
            os.environ["DATABASE_URL"] = db_url
            os.environ["DB_ADMIN_URL"] = db_url
            get_settings.cache_clear()

            from alembic import command
            from alembic.config import Config

            cfg = Config("alembic.ini")
            cfg.set_main_option("script_location", "alembic")
            command.upgrade(cfg, DOWN_REVISION)

            engine = create_engine(db_url, future=True)

            requester_id = uuid.uuid4()
            soldier_pending_id = uuid.uuid4()  # covering soldier on the pending_approval row
            soldier_open_id = uuid.uuid4()  # invited target on the still-open row
            commander_id = uuid.uuid4()
            duty_type_id = uuid.uuid4()
            duty_location_id = uuid.uuid4()
            duty_assignment_id = uuid.uuid4()
            pending_row_id = uuid.uuid4()
            open_row_id = uuid.uuid4()
            approval_id = uuid.uuid4()

            now = datetime.now(timezone.utc)
            # The open row is deliberately created EARLIER than the
            # pending_approval row, so the assertion that pending_approval
            # wins survivorship regardless of created_at actually exercises
            # the tie-break, not just "earliest wins" by coincidence.
            open_created_at = now - timedelta(hours=1)
            pending_created_at = now - timedelta(minutes=30)

            with engine.begin() as conn:
                for sid, name in [
                    (requester_id, "Requester"),
                    (soldier_pending_id, "CoveringSoldier"),
                    (soldier_open_id, "InvitedSoldier"),
                    (commander_id, "Commander"),
                ]:
                    conn.execute(
                        text(
                            "INSERT INTO soldiers (id, personal_number, full_name, password_hash) "
                            "VALUES (:id, :pn, :name, 'x')"
                        ),
                        {"id": sid, "pn": str(sid)[:12], "name": name},
                    )

                conn.execute(
                    text(
                        "INSERT INTO duty_types (id, name, score_per_day, is_external) "
                        "VALUES (:id, 'TestDuty', 1.0, false)"
                    ),
                    {"id": duty_type_id},
                )
                conn.execute(
                    text("INSERT INTO duty_locations (id, name) VALUES (:id, 'TestLoc')"),
                    {"id": duty_location_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO duty_assignments "
                        "(id, soldier_id, duty_type_id, duty_location_id, start_date, end_date) "
                        "VALUES (:id, :sid, :dtid, :dlid, CURRENT_DATE, CURRENT_DATE)"
                    ),
                    {
                        "id": duty_assignment_id,
                        "sid": requester_id,
                        "dtid": duty_type_id,
                        "dlid": duty_location_id,
                    },
                )

                # pending_approval row: covering soldier already claimed +
                # accepted (covering_side_approved=True), awaiting manager
                # approval -- this is the "further progressed" row that must
                # win survivorship.
                conn.execute(
                    text(
                        "INSERT INTO swap_requests "
                        "(id, duty_assignment_id, duty_date, requesting_soldier_id, "
                        " target_soldier_id, covering_soldier_id, covering_side_approved, "
                        " offered_assignment_ids, status, created_at, updated_at) "
                        "VALUES (:id, :daid, CURRENT_DATE, :req, :sold, :sold, true, "
                        " '[]'::jsonb, 'pending_approval', :created, :created)"
                    ),
                    {
                        "id": pending_row_id,
                        "daid": duty_assignment_id,
                        "req": requester_id,
                        "sold": soldier_pending_id,
                        "created": pending_created_at,
                    },
                )

                # open row: a second, independent invite for the same
                # (requester, duty) that nobody has claimed yet.
                conn.execute(
                    text(
                        "INSERT INTO swap_requests "
                        "(id, duty_assignment_id, duty_date, requesting_soldier_id, "
                        " target_soldier_id, covering_soldier_id, covering_side_approved, "
                        " offered_assignment_ids, status, created_at, updated_at) "
                        "VALUES (:id, :daid, CURRENT_DATE, :req, :sold, NULL, NULL, "
                        " '[]'::jsonb, 'open', :created, :created)"
                    ),
                    {
                        "id": open_row_id,
                        "daid": duty_assignment_id,
                        "req": requester_id,
                        "sold": soldier_open_id,
                        "created": open_created_at,
                    },
                )

                # Pre-existing manager approval mid-chain on the
                # pending_approval row's covering side -- must still be
                # correctly linked via swap_candidate_id after migration.
                conn.execute(
                    text(
                        "INSERT INTO swap_manager_approvals "
                        "(id, swap_request_id, side, commander_id, chain_order, approved, approver_kind) "
                        "VALUES (:id, :reqid, 'covering', :cmd, 0, false, 'commander')"
                    ),
                    {"id": approval_id, "reqid": pending_row_id, "cmd": commander_id},
                )

            # Run the migration under test. Must not raise -- in particular,
            # the partial unique index create_index(...) at the end of
            # upgrade() must not hit a unique violation.
            command.upgrade(cfg, REVISION)

            with engine.begin() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, status, open_to_marketplace FROM swap_requests "
                        "WHERE requesting_soldier_id = :req AND duty_assignment_id = :daid"
                    ),
                    {"req": requester_id, "daid": duty_assignment_id},
                ).mappings().all()

                # (a) exactly one surviving row, status='open', and it's the
                # pending_approval row's own id (survivor tie-break).
                assert len(rows) == 1, f"expected exactly one surviving row, got {rows}"
                survivor = rows[0]
                assert survivor["status"] == "open"
                assert survivor["id"] == pending_row_id, (
                    "pending_approval row should have survived consolidation with its own id "
                    "so pre-existing SwapManagerApproval rows stay correctly linked"
                )

                # (b) two candidates, one per original row.
                candidates = conn.execute(
                    text("SELECT * FROM swap_candidates WHERE swap_request_id = :sid"),
                    {"sid": survivor["id"]},
                ).mappings().all()
                assert len(candidates) == 2

                cand_pending = next(c for c in candidates if c["soldier_id"] == soldier_pending_id)
                cand_open = next(c for c in candidates if c["soldier_id"] == soldier_open_id)

                # (c) the candidate from the original pending_approval row
                # retains its approval-progress state.
                assert cand_pending["status"] == "accepted"
                assert cand_pending["soldier_side_approved"] is True
                assert cand_pending["decided_at"] is None

                # The plain-open row's candidate is untouched: still pending.
                assert cand_open["status"] == "pending"
                assert cand_open["soldier_side_approved"] is None

                # (c, cont'd) the pre-existing SwapManagerApproval row is
                # still correctly linked, now via swap_candidate_id.
                approval = conn.execute(
                    text("SELECT * FROM swap_manager_approvals WHERE id = :id"),
                    {"id": approval_id},
                ).mappings().one()
                assert approval["swap_candidate_id"] == cand_pending["id"]
                assert approval["swap_request_id"] == survivor["id"]

            engine.dispose()
        finally:
            if saved_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = saved_database_url
            if saved_db_admin_url is None:
                os.environ.pop("DB_ADMIN_URL", None)
            else:
                os.environ["DB_ADMIN_URL"] = saved_db_admin_url
            get_settings.cache_clear()
