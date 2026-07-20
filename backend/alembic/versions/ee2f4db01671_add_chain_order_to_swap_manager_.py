"""add_chain_order_to_swap_manager_approvals

The manager-approvals routes previously read swap_manager_approvals rows
back ordered by `created_at`, trying to approximate the nearest-commander-
first order that `commander_chain_for_soldier` now guarantees. That doesn't
work: all rows for one swap's approval chain are inserted inside a single
`session.flush()`, so they share the exact same `now()` value and
`ORDER BY created_at` has no guaranteed tiebreak order. The frontend now
relies on `approvals[0]` genuinely being the nearest commander (see
DirectCommanderApproval.tsx), so this adds an explicit `chain_order` integer
column (0 = nearest commander) and backfills it for any existing rows by
re-deriving each side's chain the same way `commander_chain_for_soldier` /
the earlier `ba8eaf68d98c` backfill migration did.

Revision ID: ee2f4db01671
Revises: ba8eaf68d98c
Create Date: 2026-07-20 07:29:51.949669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee2f4db01671'
down_revision: Union[str, Sequence[str], None] = 'ba8eaf68d98c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _commander_chain_for_soldier(bind, soldier_id) -> list:
    """Replicates app.services.swaps.commander_chain_for_soldier at the SQL
    level: from the soldier's own hierarchy node, walk up to the root via
    path_ids (materialized root-first), collecting distinct commander_ids
    (excluding the soldier themself), ordered NEAREST-first by reversing
    path_ids rather than relying on the IN (...) query's row order."""
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
    node_rows = bind.execute(
        sa.text("SELECT id, commander_id FROM hierarchy_nodes WHERE id = ANY(:ids)"),
        {"ids": path_ids},
    ).fetchall()
    commander_by_node = {node_id: commander_id for node_id, commander_id in node_rows}
    seen: set = set()
    chain: list = []
    for node_id in reversed(path_ids):
        commander_id = commander_by_node.get(node_id)
        if commander_id and commander_id != soldier_id and commander_id not in seen:
            seen.add(commander_id)
            chain.append(commander_id)
    return chain


def upgrade() -> None:
    op.add_column(
        "swap_manager_approvals",
        sa.Column("chain_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    bind = op.get_bind()

    # Backfill chain_order for existing rows (from the earlier
    # ba8eaf68d98c backfill migration and from any pre-existing test data),
    # by re-deriving each swap's per-side chain and assigning order by
    # position within it. Rows outside a soldier's current chain (shouldn't
    # normally happen, but data can drift) are left at chain_order=0.
    swaps = bind.execute(
        sa.text("SELECT id, requesting_soldier_id, covering_soldier_id FROM swap_requests")
    ).fetchall()

    for swap_id, requesting_soldier_id, covering_soldier_id in swaps:
        for side, soldier_id in (
            ("requester", requesting_soldier_id),
            ("covering", covering_soldier_id),
        ):
            chain = _commander_chain_for_soldier(bind, soldier_id)
            if not chain:
                continue
            for idx, commander_id in enumerate(chain):
                bind.execute(
                    sa.text(
                        "UPDATE swap_manager_approvals "
                        "SET chain_order = :idx "
                        "WHERE swap_request_id = :rid AND side = :side AND commander_id = :cid"
                    ),
                    {"idx": idx, "rid": swap_id, "side": side, "cid": commander_id},
                )


def downgrade() -> None:
    op.drop_column("swap_manager_approvals", "chain_order")
