"""unify swap requests with candidates

Revision ID: 4a4997526f58
Revises: 990fbafee861
Create Date: 2026-07-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "4a4997526f58"
down_revision = "990fbafee861"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "swap_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("swap_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("swap_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("offered_assignment_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("soldier_side_approved", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("swap_request_id", "soldier_id", name="uq_swap_candidate_request_soldier"),
    )

    op.add_column("swap_requests", sa.Column("open_to_marketplace", sa.Boolean(), nullable=False, server_default="false"))

    # Backfill. Terminal-status rows (applied/rejected/cancelled) each become
    # their own parent + exactly one candidate — unaffected by consolidation,
    # since the new partial unique index only applies WHERE status='open'.
    #
    # status='open' AND status='pending_approval' rows both end up
    # status='open' at the parent level after this migration (see the
    # collapsing UPDATE near the end), so they must be consolidated
    # TOGETHER, not just 'open' rows in isolation — otherwise a pre-existing
    # pending_approval row and a separate open row for the same
    # (requester, duty) would both survive as 'open' parents and violate the
    # new partial unique index (uq_swap_requests_one_open_per_requester_duty)
    # created below. This is a real reachable pre-migration state:
    # sibling-cancel-on-claim only fires once a covering soldier is claimed
    # (transitioning ITS OWN row to pending_approval or applied), it never
    # touches sibling rows for the same (requester, duty) that are still
    # sitting open, so a requester who invited N specific targets and/or
    # posted to the open marketplace can have one target's row already
    # accepted (pending_approval) while others remain open.
    #
    # Each such group merges into one surviving parent, with one
    # SwapCandidate per non-null target/covering soldier in the group. If the
    # group contains a pending_approval row, it (not created_at) decides the
    # survivor: a pending_approval row represents further-progressed state
    # (a candidate already accepted and awaiting manager approval, possibly
    # with existing SwapManagerApproval rows pointed at it), so collapsing it
    # into a non-survivor that then gets deleted would silently lose that
    # approval-chain progress. Preserving its id as the survivor means the
    # re-pointing step below (which matches SwapManagerApproval rows by
    # swap_request_id) still resolves correctly with no special-casing. If a
    # group somehow has more than one pending_approval row, the earliest
    # created_at among THEM wins (tie-broken by id) — see group_survivor().
    #
    # Pure status='open' groups (no pending_approval row) never have
    # pre-existing SwapManagerApproval rows — those are only created once a
    # request reaches pending_approval or later — so consolidating them
    # never needs to re-point orphaned approval rows either.
    conn = op.get_bind()
    swap_requests_t = sa.table(
        "swap_requests",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("requesting_soldier_id", postgresql.UUID(as_uuid=True)),
        sa.column("duty_assignment_id", postgresql.UUID(as_uuid=True)),
        sa.column("target_soldier_id", postgresql.UUID(as_uuid=True)),
        sa.column("covering_soldier_id", postgresql.UUID(as_uuid=True)),
        sa.column("covering_side_approved", sa.Boolean()),
        sa.column("offered_assignment_ids", postgresql.JSONB()),
        sa.column("status", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("open_to_marketplace", sa.Boolean()),
    )
    swap_candidates_t = sa.table(
        "swap_candidates",
        sa.column("swap_request_id", postgresql.UUID(as_uuid=True)),
        sa.column("soldier_id", postgresql.UUID(as_uuid=True)),
        sa.column("source", sa.Text()),
        sa.column("status", sa.Text()),
        sa.column("offered_assignment_ids", postgresql.JSONB()),
        sa.column("soldier_side_approved", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("decided_at", sa.DateTime(timezone=True)),
    )

    all_rows = conn.execute(sa.select(swap_requests_t)).mappings().all()

    from collections import defaultdict

    open_groups: dict[tuple, list] = defaultdict(list)
    other_rows = []
    for row in all_rows:
        if row["status"] in ("open", "pending_approval"):
            open_groups[(row["requesting_soldier_id"], row["duty_assignment_id"])].append(row)
        else:
            other_rows.append(row)

    def group_survivor(group_rows: list) -> dict:
        """Pick the surviving parent row for a consolidated group.

        A pending_approval row always wins over a plain open row, regardless
        of created_at, so its id (and any SwapManagerApproval rows already
        pointed at it) is preserved. Tie-break among multiple
        pending_approval rows (or, absent any, among plain open rows) is
        earliest created_at, then id, for determinism.
        """
        pending_approval_rows = [r for r in group_rows if r["status"] == "pending_approval"]
        pool = pending_approval_rows or group_rows
        return min(pool, key=lambda r: (r["created_at"], str(r["id"])))

    ids_to_delete: list = []

    for group_rows in open_groups.values():
        survivor = group_survivor(group_rows)
        if any(r["target_soldier_id"] is None for r in group_rows):
            conn.execute(
                sa.update(swap_requests_t).where(swap_requests_t.c.id == survivor["id"])
                .values(open_to_marketplace=True)
            )
        for row in group_rows:
            soldier_id = row["covering_soldier_id"] or row["target_soldier_id"]
            if soldier_id is not None:
                # A pending_approval row's candidate has already been
                # accepted by the covering soldier and is mid manager-
                # approval — "accepted", not "pending" (matches the
                # pending -> accepted transition in
                # app/services/swaps.py:approve_soldier_side). decided_at
                # stays None: that field only gets stamped on a terminal
                # transition (applied/declined/cancelled), and "accepted" is
                # not terminal.
                candidate_status = "accepted" if row["status"] == "pending_approval" else "pending"
                conn.execute(
                    sa.insert(swap_candidates_t).values(
                        swap_request_id=survivor["id"],
                        soldier_id=soldier_id,
                        source="marketplace" if row["target_soldier_id"] is None else "invited",
                        status=candidate_status,
                        offered_assignment_ids=row["offered_assignment_ids"] or [],
                        soldier_side_approved=row["covering_side_approved"],
                        created_at=row["created_at"],
                        decided_at=None,
                    )
                )
            if row["id"] != survivor["id"]:
                ids_to_delete.append(row["id"])

    for row in other_rows:
        soldier_id = row["covering_soldier_id"] or row["target_soldier_id"]
        if soldier_id is not None:
            conn.execute(
                sa.insert(swap_candidates_t).values(
                    swap_request_id=row["id"],
                    soldier_id=soldier_id,
                    source="marketplace" if row["target_soldier_id"] is None else "invited",
                    status="applied" if row["status"] == "applied" else "cancelled",
                    offered_assignment_ids=row["offered_assignment_ids"] or [],
                    soldier_side_approved=row["covering_side_approved"],
                    created_at=row["created_at"],
                    decided_at=row["updated_at"],
                )
            )
        if row["target_soldier_id"] is None:
            conn.execute(
                sa.update(swap_requests_t).where(swap_requests_t.c.id == row["id"])
                .values(open_to_marketplace=True)
            )

    if ids_to_delete:
        conn.execute(sa.delete(swap_requests_t).where(swap_requests_t.c.id.in_(ids_to_delete)))

    # Re-point covering-side SwapManagerApproval rows at the new candidate.
    # This join matches on swap_request_id, so it only re-points approvals
    # whose parent row kept its own id: that's every `other_rows` row (they
    # were never merged), and, within a merged open_groups group, the
    # pending_approval row when present (group_survivor always keeps it as
    # the survivor, by id, specifically so this still works). Plain 'open'
    # rows never have pre-existing SwapManagerApproval rows to begin with
    # (those only exist once a request reaches pending_approval or later),
    # so a plain-open non-survivor being deleted below never orphans any
    # approval. A group can only ever contain a single live pending_approval
    # row pre-migration — claim_request cancels every other still-live
    # sibling (open or pending_approval) the moment one of them claims — so
    # there is no scenario where a non-survivor row in a group still holds
    # approvals that this join would fail to reach.
    op.add_column("swap_manager_approvals", sa.Column("swap_candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("swap_candidates.id", ondelete="CASCADE"), nullable=True))
    op.execute("""
        UPDATE swap_manager_approvals sma
        SET swap_candidate_id = sc.id
        FROM swap_candidates sc
        WHERE sma.side = 'covering' AND sma.swap_request_id = sc.swap_request_id;
    """)

    op.drop_constraint("uq_swap_manager_approval_request_side_person_kind", "swap_manager_approvals", type_="unique")
    op.create_unique_constraint(
        "uq_swap_manager_approval_request_candidate_side_person_kind",
        "swap_manager_approvals",
        ["swap_request_id", "swap_candidate_id", "side", "commander_id", "approver_kind"],
    )

    op.drop_column("swap_requests", "target_soldier_id")
    op.drop_column("swap_requests", "covering_soldier_id")
    op.drop_column("swap_requests", "covering_side_approved")
    op.drop_column("swap_requests", "offered_assignment_ids")

    # status no longer includes 'pending_approval' at the parent level. The
    # backfill above never rewrote a surviving pending_approval row's own
    # status column (it only inserted candidates, set open_to_marketplace,
    # and deleted non-survivors), so every surviving pending_approval row
    # still literally reads 'pending_approval' at this point — this is what
    # collapses them to 'open', now that "in progress" state lives on the
    # SwapCandidate (status='accepted') instead of the parent row.
    op.execute("UPDATE swap_requests SET status = 'open' WHERE status = 'pending_approval';")

    op.create_index(
        "uq_swap_requests_one_open_per_requester_duty",
        "swap_requests",
        ["requesting_soldier_id", "duty_assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_swap_requests_one_open_per_requester_duty", table_name="swap_requests")
    op.add_column("swap_requests", sa.Column("target_soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True))
    op.add_column("swap_requests", sa.Column("covering_soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True))
    op.add_column("swap_requests", sa.Column("covering_side_approved", sa.Boolean(), nullable=True))
    op.add_column("swap_requests", sa.Column("offered_assignment_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.drop_constraint("uq_swap_manager_approval_request_candidate_side_person_kind", "swap_manager_approvals", type_="unique")
    op.create_unique_constraint(
        "uq_swap_manager_approval_request_side_person_kind",
        "swap_manager_approvals",
        ["swap_request_id", "side", "commander_id", "approver_kind"],
    )
    op.drop_column("swap_manager_approvals", "swap_candidate_id")
    op.drop_column("swap_requests", "open_to_marketplace")
    op.drop_table("swap_candidates")
