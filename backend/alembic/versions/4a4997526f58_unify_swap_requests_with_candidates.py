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

    # Backfill. Terminal-status rows (applied/rejected/cancelled) and rows
    # that already reached pending_approval each become their own parent +
    # exactly one candidate — unaffected by consolidation, since the new
    # partial unique index only applies WHERE status='open'.
    #
    # status='open' rows need consolidation: sibling-cancel-on-claim only
    # fires once a covering soldier is claimed (transitioning the row to
    # pending_approval or applied) — it never ran at request-creation time,
    # so a requester who invited N specific targets and/or posted to the
    # open marketplace, with nobody having claimed yet, genuinely has N
    # simultaneously-open rows for the same (requester, duty) today. Each
    # group of open rows for the same (requester, duty) must merge into one
    # surviving parent (earliest created_at, tie-broken by id) with one
    # SwapCandidate per non-null target/covering soldier in the group.
    # status='open' rows never have pre-existing SwapManagerApproval rows —
    # those are only created once a request reaches pending_approval or
    # later — so this consolidation never needs to re-point orphaned
    # approval rows; the re-pointing step below only concerns the
    # non-open/terminal rows, which keep their own id.
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
        if row["status"] == "open":
            open_groups[(row["requesting_soldier_id"], row["duty_assignment_id"])].append(row)
        else:
            other_rows.append(row)

    ids_to_delete: list = []

    for group_rows in open_groups.values():
        survivor = min(group_rows, key=lambda r: (r["created_at"], str(r["id"])))
        if any(r["target_soldier_id"] is None for r in group_rows):
            conn.execute(
                sa.update(swap_requests_t).where(swap_requests_t.c.id == survivor["id"])
                .values(open_to_marketplace=True)
            )
        for row in group_rows:
            soldier_id = row["covering_soldier_id"] or row["target_soldier_id"]
            if soldier_id is not None:
                conn.execute(
                    sa.insert(swap_candidates_t).values(
                        swap_request_id=survivor["id"],
                        soldier_id=soldier_id,
                        source="marketplace" if row["target_soldier_id"] is None else "invited",
                        status="pending",
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
    # Only ever matters for the `other_rows` path above (rows that reached
    # pending_approval or later keep their own id, so this join still
    # resolves correctly) — the open-group consolidation path has nothing
    # to re-point, per the note above.
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

    # status no longer includes 'pending_approval' at the parent level —
    # collapse any lingering value (shouldn't exist after the backfill above
    # touches every non-open/applied/rejected/cancelled row, but guard anyway).
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
