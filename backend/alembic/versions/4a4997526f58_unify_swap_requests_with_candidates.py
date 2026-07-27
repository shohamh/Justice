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
    # created below. This is a real reachable pre-migration state, for two
    # independent reasons:
    #   * claim_request DOES cancel siblings, but only AFTER a claim: it
    #     cancels every other row for the same (requester, duty) with status
    #     in ('open', 'pending_approval'). Until someone claims, a requester
    #     who invited N specific targets and/or also posted to the open
    #     marketplace simply has N+1 live open rows.
    #   * cover_offer does NOT cancel siblings at all — it flips only its own
    #     row to pending_approval. So a covered row can sit at
    #     pending_approval indefinitely alongside untouched open siblings, and
    #     two separate cover_offers can even leave two live pending_approval
    #     rows in the same group.
    # This asymmetry is also what makes it possible for the SAME soldier to
    # appear in two rows of one group (invited on one row, covering on
    # another) — hence the per-soldier dedup in the loop below.
    #
    # Each such group merges into one surviving parent, with one
    # SwapCandidate per non-null target/covering soldier in the group. If the
    # group contains a pending_approval row, it (not created_at) decides the
    # survivor: a pending_approval row represents further-progressed state
    # (a candidate already accepted and awaiting manager approval, possibly
    # with existing SwapManagerApproval rows pointed at it), so collapsing it
    # into a non-survivor that then gets deleted would silently lose that
    # approval-chain progress. Preserving its id as the survivor means the
    # re-pointing step below still resolves correctly with no special-casing.
    # A group can genuinely hold more than one pending_approval row (two
    # cover_offer claims on two sibling rows — cover_offer never cancels
    # siblings); in that case the earliest created_at among THEM wins,
    # tie-broken by id — see group_survivor().
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

        # The SAME soldier can appear in more than one row of a group, so
        # candidates must be deduplicated by soldier_id before insert —
        # swap_candidates carries UniqueConstraint(swap_request_id,
        # soldier_id) and a second insert would abort the whole migration.
        #
        # Reachable pre-branch: a requester invites X (row_X,
        # target_soldier_id=X) and also posts the same duty to the open
        # marketplace (row_M, target_soldier_id=NULL) — permitted, because
        # create_request's `already_pending` check only matched on the literal
        # target, not on "any open row for this (requester, duty)". X then
        # claims the anonymous marketplace posting through cover_offer, which
        # (unlike claim_request) does NOT cancel sibling rows — see the
        # SwapManagerApproval note further below. Now X is in the group twice:
        # once as row_X.target_soldier_id and once as
        # row_M.covering_soldier_id.
        #
        # Ordering below decides which row represents the soldier: a
        # pending_approval row outranks a plain open one (it carries real
        # progress — soldier_side_approved, and possibly SwapManagerApproval
        # rows), then earliest created_at, then id, for determinism. `source`
        # is decided independently of that pick: if the soldier appears as an
        # explicit target_soldier_id in ANY row of the group they are
        # "invited", since the requester naming them is a stronger statement
        # of intent than an anonymous marketplace claim by the same person.
        invited_soldier_ids = {
            r["target_soldier_id"] for r in group_rows if r["target_soldier_id"] is not None
        }
        ordered_rows = sorted(
            group_rows,
            key=lambda r: (0 if r["status"] == "pending_approval" else 1, r["created_at"], str(r["id"])),
        )
        row_by_soldier: dict = {}
        for row in ordered_rows:
            soldier_id = row["covering_soldier_id"] or row["target_soldier_id"]
            if soldier_id is not None:
                row_by_soldier.setdefault(soldier_id, row)

        for soldier_id, row in row_by_soldier.items():
            # A pending_approval row's candidate has already been accepted by
            # the covering soldier and is mid manager-approval — "accepted",
            # not "pending" (matches the pending -> accepted transition in
            # app/services/swaps.py:approve_soldier_side). decided_at stays
            # None: that field only gets stamped on a terminal transition
            # (applied/declined/cancelled), and "accepted" is not terminal.
            candidate_status = "accepted" if row["status"] == "pending_approval" else "pending"
            conn.execute(
                sa.insert(swap_candidates_t).values(
                    swap_request_id=survivor["id"],
                    soldier_id=soldier_id,
                    source="invited" if soldier_id in invited_soldier_ids else "marketplace",
                    status=candidate_status,
                    offered_assignment_ids=row["offered_assignment_ids"] or [],
                    soldier_side_approved=row["covering_side_approved"],
                    created_at=row["created_at"],
                    decided_at=None,
                )
            )

        for row in group_rows:
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
    #
    # Which parents can still hold approvals here: only rows that kept their
    # own id. That's every `other_rows` row (terminal — never merged), and,
    # within a merged open_groups group, the pending_approval row when present
    # (group_survivor always keeps it as the survivor, by id, specifically so
    # this still resolves). Plain 'open' rows never have pre-existing
    # SwapManagerApproval rows at all — those only get created once a request
    # reaches pending_approval or later — so deleting a plain-open non-survivor
    # below never orphans an approval.
    #
    # A group CAN contain more than one pending_approval row, so this must not
    # be assumed away. The two pre-branch claim paths differ:
    #   * claim_request DOES cancel siblings — after claiming it cancels every
    #     other row for the same (requester, duty) whose status is in
    #     ('open', 'pending_approval').
    #   * cover_offer does NOT — it flips only its own row to
    #     pending_approval and leaves every sibling exactly as it was.
    # So two soldiers each cover_offer-ing two different rows of the same
    # (requester, duty) leaves two live pending_approval rows in one group.
    # That is also precisely why the same soldier can appear twice in a group
    # (see the dedup block above): an invite row plus a marketplace row that
    # the invited soldier then cover_offer-ed.
    #
    # Because a group can therefore end up with several candidates under one
    # surviving parent, the join is qualified by soldier: an approval is
    # re-pointed at the candidate for ITS OWN row's covering soldier, not at
    # whichever candidate the planner happens to match first.
    op.add_column("swap_manager_approvals", sa.Column("swap_candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("swap_candidates.id", ondelete="CASCADE"), nullable=True))
    op.execute("""
        UPDATE swap_manager_approvals sma
        SET swap_candidate_id = sc.id
        FROM swap_requests sr, swap_candidates sc
        WHERE sma.side = 'covering'
          AND sma.swap_request_id = sr.id
          AND sc.swap_request_id = sr.id
          AND sc.soldier_id = sr.covering_soldier_id;
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
