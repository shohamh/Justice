"""backfill_swap_manager_approvals_for_inflight_swaps

Any swap already sitting in ``pending_approval`` when the chain-of-command
approval feature (and this follow-up "any one commander suffices" semantics
fix) shipped has zero ``swap_manager_approvals`` rows — those are only
created at ``claim_request``/``cover_offer`` time, which already happened for
these swaps under the old code. Their ``requester_side_approved`` /
``covering_side_approved`` booleans also carry the OLD meaning ("manager
approved") rather than the new meaning ("soldier approved"), so they can't be
trusted either.

This migration, for every in-flight ``pending_approval`` swap:
  - resets both side-approved booleans to false (there's no way to know
    whether the actual soldiers involved would approve under the new flow,
    so we err on the safe side and require them to approve fresh), and
  - walks each side's commander chain (mirroring
    ``app.services.swaps.commander_chain_for_soldier`` /
    ``_create_manager_approval_rows`` at the SQL level) and creates the
    missing ``swap_manager_approvals`` rows, same as claim/cover-offer would
    have done had the feature existed when the swap was claimed.

Revision ID: ba8eaf68d98c
Revises: b388b74fdae9
Create Date: 2026-07-19 22:42:40.317084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba8eaf68d98c'
down_revision: Union[str, Sequence[str], None] = 'b388b74fdae9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _commander_chain_for_soldier(bind, soldier_id) -> list:
    """Replicates app.services.swaps.commander_chain_for_soldier at the SQL
    level: from the soldier's own hierarchy node, walk up to the root via
    path_ids, collecting distinct commander_ids (excluding the soldier
    themself, in case they command their own node)."""
    if soldier_id is None:
        return []
    soldier_row = bind.execute(
        sa.text("SELECT hierarchy_node_id FROM soldiers WHERE id = :sid"),
        {"sid": soldier_id},
    ).first()
    if soldier_row is None or soldier_row[0] is None:
        return []
    node_row = bind.execute(
        sa.text("SELECT path_ids FROM hierarchy_nodes WHERE id = :nid"),
        {"nid": soldier_row[0]},
    ).first()
    if node_row is None or not node_row[0]:
        return []
    path_ids = list(node_row[0])
    chain_rows = bind.execute(
        sa.text("SELECT commander_id FROM hierarchy_nodes WHERE id = ANY(:ids)"),
        {"ids": path_ids},
    ).fetchall()
    seen: set = set()
    chain: list = []
    for (commander_id,) in chain_rows:
        if commander_id and commander_id != soldier_id and commander_id not in seen:
            seen.add(commander_id)
            chain.append(commander_id)
    return chain


def upgrade() -> None:
    bind = op.get_bind()

    swaps = bind.execute(
        sa.text(
            "SELECT id, requesting_soldier_id, covering_soldier_id "
            "FROM swap_requests WHERE status = 'pending_approval'"
        )
    ).fetchall()

    for swap_id, requesting_soldier_id, covering_soldier_id in swaps:
        bind.execute(
            sa.text(
                "UPDATE swap_requests "
                "SET requester_side_approved = false, covering_side_approved = false "
                "WHERE id = :id"
            ),
            {"id": swap_id},
        )
        for side, soldier_id in (
            ("requester", requesting_soldier_id),
            ("covering", covering_soldier_id),
        ):
            for commander_id in _commander_chain_for_soldier(bind, soldier_id):
                already_exists = bind.execute(
                    sa.text(
                        "SELECT 1 FROM swap_manager_approvals "
                        "WHERE swap_request_id = :rid AND side = :side AND commander_id = :cid"
                    ),
                    {"rid": swap_id, "side": side, "cid": commander_id},
                ).first()
                if already_exists:
                    continue
                bind.execute(
                    sa.text(
                        "INSERT INTO swap_manager_approvals (id, swap_request_id, side, commander_id) "
                        "VALUES (gen_random_uuid(), :rid, :side, :cid)"
                    ),
                    {"rid": swap_id, "side": side, "cid": commander_id},
                )


def downgrade() -> None:
    # Data migration — not reversed. Re-clearing requester/covering approval
    # booleans or deleting the backfilled swap_manager_approvals rows would
    # destroy real in-flight approval progress collected after this migration
    # ran, with no way to recover the pre-migration (already-stale) state.
    pass
