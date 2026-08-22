"""Backfill tests for migration 4a4997526f58 (unify swap requests with candidates).

Runs the migration's backfill logic against a clone of the shared
migration-template database (tests/support/database.py), independent of the
session-scoped conftest container: that container is already migrated straight
to head before any test runs, so there's no way to seed pre-migration rows
against it. These tests run against a fresh clone migrated to the migration's
own down_revision, seed rows in the OLD two-party swap_requests schema,
upgrade one more step to the migration under test, and assert on the resulting
swap_requests / swap_candidates / swap_manager_approvals rows.

Covered:

* the gap where a pre-existing `pending_approval` row and a separate `open`
  row for the same (requesting_soldier_id, duty_assignment_id) were NOT
  consolidated by the original backfill (only same-status rows were grouped),
  so both would end up status='open' after migration -- violating the new
  partial unique index `uq_swap_requests_one_open_per_requester_duty` and,
  worse, resurrecting the exact two-live-open-parents state this whole
  migration exists to eliminate.

* the gap where the SAME soldier appeared twice inside one consolidated group
  (as one row's target_soldier_id and another row's covering_soldier_id), so
  the backfill inserted two SwapCandidate rows for them and blew up on
  `uq_swap_candidate_request_soldier` mid-`alembic upgrade`.
"""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.support import database as db_support

DOWN_REVISION = "990fbafee861"
REVISION = "4a4997526f58"

pytestmark = pytest.mark.slow

_TEMPLATE = None


@contextmanager
def _db_at_down_revision():
    """Fresh clone of the cached template migrated to DOWN_REVISION, plus a
    callable that steps it one more revision (onto REVISION).

    The shared harness temporarily repoints DATABASE_URL/DB_ADMIN_URL and
    clears the lru_cache'd app settings singleton for the body, restoring
    them afterwards so later tests in this worker process see the original
    (shared container) settings again.
    """
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = db_support.get_migrated_template(
            DOWN_REVISION, Path(__file__).resolve().parents[2]
        )
    with db_support.cloned_migration_database(
        _TEMPLATE, upgrade_to_revision=REVISION, rootpath=Path(__file__).resolve().parents[2]
    ) as (engine, run_migration):
        yield engine, run_migration


def _seed_soldier(conn, sid, name):
    conn.execute(
        text(
            "INSERT INTO soldiers (id, personal_number, full_name, password_hash) "
            "VALUES (:id, :pn, :name, 'x')"
        ),
        {"id": sid, "pn": str(sid)[:12], "name": name},
    )


def _seed_assignment(conn, *, assignment_id, soldier_id, suffix):
    duty_type_id = uuid.uuid4()
    duty_location_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO duty_types (id, name, score_per_day, is_external) "
            "VALUES (:id, :name, 1.0, false)"
        ),
        {"id": duty_type_id, "name": f"TestDuty{suffix}"},
    )
    conn.execute(
        text("INSERT INTO duty_locations (id, name) VALUES (:id, :name)"),
        {"id": duty_location_id, "name": f"TestLoc{suffix}"},
    )
    conn.execute(
        text(
            "INSERT INTO duty_assignments "
            "(id, soldier_id, duty_type_id, duty_location_id, start_date, end_date) "
            "VALUES (:id, :sid, :dtid, :dlid, CURRENT_DATE, CURRENT_DATE)"
        ),
        {
            "id": assignment_id,
            "sid": soldier_id,
            "dtid": duty_type_id,
            "dlid": duty_location_id,
        },
    )


_INSERT_SWAP_ROW = text(
    "INSERT INTO swap_requests "
    "(id, duty_assignment_id, duty_date, requesting_soldier_id, "
    " target_soldier_id, covering_soldier_id, covering_side_approved, "
    " offered_assignment_ids, status, created_at, updated_at) "
    "VALUES (:id, :daid, CURRENT_DATE, :req, :target, :covering, :cov_approved, "
    " '[]'::jsonb, :status, :created, :created)"
)


def test_pending_approval_and_open_row_same_requester_duty_consolidate():
    """Seed one pending_approval row and one open row for the same
    (requester, duty) pre-migration; assert the backfill merges them into a
    single surviving open parent instead of leaving two open rows.
    """
    with _db_at_down_revision() as (engine, run_migration):
        requester_id = uuid.uuid4()
        soldier_pending_id = uuid.uuid4()  # covering soldier on the pending_approval row
        soldier_open_id = uuid.uuid4()  # invited target on the still-open row
        commander_id = uuid.uuid4()
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
                _seed_soldier(conn, sid, name)

            _seed_assignment(conn, assignment_id=duty_assignment_id, soldier_id=requester_id, suffix="A")

            # pending_approval row: covering soldier already claimed +
            # accepted (covering_side_approved=True), awaiting manager
            # approval -- this is the "further progressed" row that must
            # win survivorship.
            conn.execute(
                _INSERT_SWAP_ROW,
                {
                    "id": pending_row_id,
                    "daid": duty_assignment_id,
                    "req": requester_id,
                    "target": soldier_pending_id,
                    "covering": soldier_pending_id,
                    "cov_approved": True,
                    "status": "pending_approval",
                    "created": pending_created_at,
                },
            )

            # open row: a second, independent invite for the same
            # (requester, duty) that nobody has claimed yet.
            conn.execute(
                _INSERT_SWAP_ROW,
                {
                    "id": open_row_id,
                    "daid": duty_assignment_id,
                    "req": requester_id,
                    "target": soldier_open_id,
                    "covering": None,
                    "cov_approved": None,
                    "status": "open",
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
        run_migration()

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
            # still correctly linked, now via swap_candidate_id -- and
            # specifically to ITS OWN row's covering soldier, not to
            # whichever of the group's two candidates the planner happened
            # to join first.
            approval = conn.execute(
                text("SELECT * FROM swap_manager_approvals WHERE id = :id"),
                {"id": approval_id},
            ).mappings().one()
            assert approval["swap_candidate_id"] == cand_pending["id"]
            assert approval["swap_request_id"] == survivor["id"]


def test_same_soldier_in_two_rows_of_a_group_yields_one_candidate():
    """The same soldier can legitimately appear twice inside one consolidated
    group: the requester invites X (row_X.target_soldier_id = X) AND posts the
    same duty to the open marketplace (row_M.target_soldier_id IS NULL), then X
    covers the anonymous marketplace posting (row_M.covering_soldier_id = X).
    Pre-branch this was reachable because create_request's `already_pending`
    check only matched on the literal target, and cover_offer -- unlike
    claim_request -- never cancels sibling rows.

    Without per-soldier dedup the backfill inserts two SwapCandidate rows for
    X under one surviving parent and aborts the whole `alembic upgrade` on
    uq_swap_candidate_request_soldier.

    Two variants are seeded, in two independent (requester, duty) groups:
      * group 1 -- row_M reached pending_approval (the realistic cover_offer
        outcome when swaps.require_manager_approval is on). Exercises both
        tie-breaks at once: the surviving candidate must take the
        most-progressed row's state, but the "invited" source from the other
        row.
      * group 2 -- both rows still plain 'open'. Same dedup, simpler state.
    """
    with _db_at_down_revision() as (engine, run_migration):
        # group 1
        requester1_id = uuid.uuid4()
        x_id = uuid.uuid4()
        assignment1_id = uuid.uuid4()
        g1_invited_row_id = uuid.uuid4()
        g1_marketplace_row_id = uuid.uuid4()
        # group 2
        requester2_id = uuid.uuid4()
        y_id = uuid.uuid4()
        assignment2_id = uuid.uuid4()
        g2_invited_row_id = uuid.uuid4()
        g2_marketplace_row_id = uuid.uuid4()

        now = datetime.now(timezone.utc)
        invited_created_at = now - timedelta(hours=2)
        marketplace_created_at = now - timedelta(hours=1)

        with engine.begin() as conn:
            for sid, name in [
                (requester1_id, "Requester1"),
                (x_id, "SoldierX"),
                (requester2_id, "Requester2"),
                (y_id, "SoldierY"),
            ]:
                _seed_soldier(conn, sid, name)
            _seed_assignment(conn, assignment_id=assignment1_id, soldier_id=requester1_id, suffix="1")
            _seed_assignment(conn, assignment_id=assignment2_id, soldier_id=requester2_id, suffix="2")

            # --- group 1: invited(open) + marketplace(pending_approval by X)
            conn.execute(
                _INSERT_SWAP_ROW,
                {
                    "id": g1_invited_row_id, "daid": assignment1_id, "req": requester1_id,
                    "target": x_id, "covering": None, "cov_approved": None,
                    "status": "open", "created": invited_created_at,
                },
            )
            conn.execute(
                _INSERT_SWAP_ROW,
                {
                    "id": g1_marketplace_row_id, "daid": assignment1_id, "req": requester1_id,
                    "target": None, "covering": x_id, "cov_approved": True,
                    "status": "pending_approval", "created": marketplace_created_at,
                },
            )

            # --- group 2: invited(open) + marketplace(open, covering = Y)
            conn.execute(
                _INSERT_SWAP_ROW,
                {
                    "id": g2_invited_row_id, "daid": assignment2_id, "req": requester2_id,
                    "target": y_id, "covering": None, "cov_approved": None,
                    "status": "open", "created": invited_created_at,
                },
            )
            conn.execute(
                _INSERT_SWAP_ROW,
                {
                    "id": g2_marketplace_row_id, "daid": assignment2_id, "req": requester2_id,
                    "target": None, "covering": y_id, "cov_approved": None,
                    "status": "open", "created": marketplace_created_at,
                },
            )

        # (a) must not raise: pre-fix this died on
        # uq_swap_candidate_request_soldier partway through upgrade().
        run_migration()

        with engine.begin() as conn:
            for requester_id, assignment_id, soldier_id, expected_status, expected_side_approved in [
                (requester1_id, assignment1_id, x_id, "accepted", True),
                (requester2_id, assignment2_id, y_id, "pending", None),
            ]:
                # (b) exactly one surviving SwapRequest for the group
                rows = conn.execute(
                    text(
                        "SELECT id, status, open_to_marketplace FROM swap_requests "
                        "WHERE requesting_soldier_id = :req AND duty_assignment_id = :daid"
                    ),
                    {"req": requester_id, "daid": assignment_id},
                ).mappings().all()
                assert len(rows) == 1, f"expected one surviving row, got {rows}"
                survivor = rows[0]
                assert survivor["status"] == "open"
                # the group contained a target_soldier_id IS NULL row
                assert survivor["open_to_marketplace"] is True

                # (c) exactly ONE candidate for that soldier, not two
                candidates = conn.execute(
                    text("SELECT * FROM swap_candidates WHERE swap_request_id = :sid"),
                    {"sid": survivor["id"]},
                ).mappings().all()
                assert len(candidates) == 1, f"expected one deduplicated candidate, got {candidates}"
                cand = candidates[0]
                assert cand["soldier_id"] == soldier_id

                # (d) an explicit invite anywhere in the group beats an
                # anonymous marketplace claim by the same soldier.
                assert cand["source"] == "invited"

                # ...and the most-progressed row in the group supplies the
                # candidate's own state.
                assert cand["status"] == expected_status
                assert cand["soldier_side_approved"] is expected_side_approved
