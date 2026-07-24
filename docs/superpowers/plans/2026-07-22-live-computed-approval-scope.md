# Live-Computed Approval Scope Implementation Plan (Part A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the swap-request approval chain's pre-populated `SwapManagerApproval` roster with live-computed commander/duty-manager scope (fixing org-wide duty-manager scoping, generalizing the one-click-resolves-everything rule, adding per-decision rejection attribution, and auto-approving the soldier's own side on ask/cover), and extend the same live lookup to the other 4 request types for display only (no approval-policy change).

**Architecture:** A new `app/services/approval_scope.py` provides two pure, live query functions (`commander_chain_for_soldier`, `duty_manager_chain_for_soldier`) with no DB writes. Swaps stop pre-populating the full roster (`_create_manager_approval_rows` deleted) and instead create `SwapManagerApproval` rows lazily, one at a time, only when a real approve/reject happens — a pure decision log. Satisfaction checks (`_all_approved`) and eligibility checks (`is_chain_commander_for_side`) both become live computations against the current chain, cross-referenced with whatever decision rows already exist. The other 4 request types get two new read-only response fields (`nearest_commander`, `nearest_duty_manager`) computed the same way, with zero change to their existing authorization/approval-count logic. The frontend already has a working `DirectCommanderApproval`/`groupByKind` component (`frontend/src/components/DirectCommanderApproval.tsx`) driven entirely by a small structural row list — reused as-is for both swaps (already wired) and the other 4 types (newly wired), no new component needed.

**Tech Stack:** FastAPI/SQLAlchemy backend (Python 3.12+), React/TypeScript frontend, pytest, Alembic.

## Global Constraints

- Nothing about the required-approver roster is ever pre-written to the database — only actual decisions (approve/reject) get persisted, and only for the specific person who made them.
- Once a decision is recorded, it is a permanent fact — it does not get invalidated if the org chart changes later. "Live" governs what is *currently required* and who is *currently eligible to click*, not re-litigation of past decisions.
- Exemption/constraint/field-update/enrollment requests get **zero change** to their existing authorization (`Action`/`authorize()`) or approval-count policy — additions are purely new read-only display fields.
- External call sites of `approve_manager_side`/`reject_request`/routes (`backend/app/routes/notifications.py`, `backend/app/routes/swaps.py`) keep their existing signatures — only the internal bodies of the functions they call change.
- One click by a person resolves every `(side, approver_kind)` combination they are currently eligible for on that swap request, in a single call — no special-casing for "same person both sides" or "same person both kinds."

---

### Task 1: `app/services/approval_scope.py` — shared live-computation service

**Files:**
- Create: `backend/app/services/approval_scope.py`
- Modify: `backend/app/services/swaps.py:223-255` (remove `commander_chain_for_soldier`, import it instead)
- Test: `backend/app/services/tests/test_approval_scope.py` (new)

**Interfaces:**
- Produces: `commander_chain_for_soldier(session, soldier_id) -> list[uuid.UUID]`, `duty_manager_chain_for_soldier(session, soldier_id) -> list[uuid.UUID]`, `nearest_commander_for_soldier(session, soldier_id) -> uuid.UUID | None`, `nearest_duty_manager_for_soldier(session, soldier_id) -> uuid.UUID | None` — consumed by every later task in this plan.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_approval_scope.py
from __future__ import annotations

import uuid

from app.db.models import DutyManagerScope
from app.services.approval_scope import (
    commander_chain_for_soldier,
    duty_manager_chain_for_soldier,
    nearest_commander_for_soldier,
    nearest_duty_manager_for_soldier,
)
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_duty_manager_chain_empty_when_no_scope_assigned(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()

    assert duty_manager_chain_for_soldier(admin_session, soldier.id) == []
    assert nearest_duty_manager_for_soldier(admin_session, soldier.id) is None


def test_duty_manager_chain_includes_scope_holder_of_soldiers_own_node(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    chain = duty_manager_chain_for_soldier(admin_session, soldier.id)
    assert chain == [dm.id]
    assert nearest_duty_manager_for_soldier(admin_session, soldier.id) == dm.id


def test_duty_manager_chain_walks_to_root_nearest_first(admin_session):
    root = create_node(admin_session, level="branch", name=f"root_{_uid()}")
    child = create_node(admin_session, level="unit", name=f"child_{_uid()}", parent_id=root.id)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=child.id)
    near_dm = create_soldier(admin_session, personal_number=f"near_{_uid()}", role="duty_manager")
    far_dm = create_soldier(admin_session, personal_number=f"far_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=near_dm.id, hierarchy_node_id=child.id))
    admin_session.add(DutyManagerScope(duty_manager_id=far_dm.id, hierarchy_node_id=root.id))
    admin_session.commit()

    chain = duty_manager_chain_for_soldier(admin_session, soldier.id)
    assert chain == [near_dm.id, far_dm.id]


def test_duty_manager_chain_does_not_leak_out_of_scope_managers(admin_session):
    in_node = create_node(admin_session, level="unit", name=f"in_{_uid()}")
    out_node = create_node(admin_session, level="unit", name=f"out_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=in_node.id)
    out_dm = create_soldier(admin_session, personal_number=f"out_dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=out_dm.id, hierarchy_node_id=out_node.id))
    admin_session.commit()

    assert duty_manager_chain_for_soldier(admin_session, soldier.id) == []


def test_commander_chain_still_importable_from_new_module(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    commander = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()

    assert commander_chain_for_soldier(admin_session, soldier.id) == [commander.id]
    assert nearest_commander_for_soldier(admin_session, soldier.id) == commander.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`, venv active): `pytest app/services/tests/test_approval_scope.py -v`
Expected: FAIL — `app.services.approval_scope` doesn't exist yet.

- [ ] **Step 3: Create the module**

```python
# backend/app/services/approval_scope.py
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, HierarchyNode, Soldier


def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct commander from the soldier's own node up to the root of
    the hierarchy, excluding the soldier themself if they command their own node.

    Ordered NEAREST-commander-first: chain[0] is the closest ancestor (or the
    soldier's own node) that has a commander, and the list walks outward to
    the root from there. `node.path_ids` is materialized root-first (see
    `hierarchy.py`: `node.path_ids = [*parent.path_ids, node.id]`), so we
    reorder via `reversed(node.path_ids)` rather than relying on the `IN (...)`
    query's row order, which SQL does not guarantee to match the list order.

    Moved here (from app/services/swaps.py) so every request type — not just
    swaps — can share it without importing swaps.py.
    """
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
        ).scalars().all()
    }
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        n = nodes_by_id.get(node_id)
        if n is None:
            continue
        if n.commander_id and n.commander_id != soldier_id and n.commander_id not in seen:
            seen.add(n.commander_id)
            chain.append(n.commander_id)
    return chain


def duty_manager_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct duty manager whose DutyManagerScope covers the soldier's
    node or one of its ancestors — nearest-scope-first, mirroring
    commander_chain_for_soldier's walk. A single node can have more than one
    duty manager scoped to it (unlike commander_id, which is 0-or-1); within
    one node's group, order by full_name for determinism (no other natural
    order exists at that granularity)."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    scopes = session.execute(
        select(DutyManagerScope).where(DutyManagerScope.hierarchy_node_id.in_(node.path_ids))
    ).scalars().all()
    by_node: dict[uuid.UUID, list[uuid.UUID]] = {}
    for s in scopes:
        by_node.setdefault(s.hierarchy_node_id, []).append(s.duty_manager_id)
    dm_ids_needing_names = {dm_id for ids in by_node.values() for dm_id in ids}
    names_by_id = {
        s.id: s.full_name
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_(dm_ids_needing_names))
        ).scalars().all()
    } if dm_ids_needing_names else {}
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        for dm_id in sorted(by_node.get(node_id, []), key=lambda i: names_by_id.get(i, "")):
            if dm_id not in seen:
                seen.add(dm_id)
                chain.append(dm_id)
    return chain


def nearest_commander_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = commander_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None


def nearest_duty_manager_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = duty_manager_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None
```

- [ ] **Step 4: Remove `commander_chain_for_soldier` from `swaps.py` and import it instead**

In `backend/app/services/swaps.py`, delete the function body at lines 223-255 and add to the imports at the top of the file:

```python
from app.services.approval_scope import commander_chain_for_soldier, duty_manager_chain_for_soldier
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest app/services/tests/test_approval_scope.py -v`
Expected: PASS

- [ ] **Step 6: Run the existing swaps test file to check nothing broke from the import move**

Run: `pytest app/services/tests/test_swaps.py -v`
Expected: PASS (the commander-chain tests in this file, e.g. `test_commander_chain_walks_to_root`, will need their import statement updated if they import `commander_chain_for_soldier` directly from `app.services.swaps` — check and fix any such import to `app.services.approval_scope` instead; the function itself is unchanged, only its location moved)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/approval_scope.py backend/app/services/swaps.py backend/app/services/tests/test_approval_scope.py backend/app/services/tests/test_swaps.py
git commit -m "feat: extract shared live commander/duty-manager scope lookup"
```

---

### Task 2: Migration — decision-log columns

**Files:**
- Create: `backend/alembic/versions/<new_revision>_swap_approval_decision_log.py`
- Modify: `backend/app/db/models.py:536-569` (`SwapManagerApproval`), `:493-534` (`SwapRequest`)

**Interfaces:**
- Produces: `SwapManagerApproval.rejected: bool`, `.rejected_by: uuid.UUID | None`, `.rejected_at: datetime | None`; `SwapRequest.rejected_by: uuid.UUID | None`; a unique constraint on `SwapManagerApproval(swap_request_id, side, commander_id, approver_kind)` — consumed by Task 3.

- [ ] **Step 1: Add the new columns to the models**

In `backend/app/db/models.py`, `SwapManagerApproval` (after the existing `decision_note` column, before `approver_kind`):

```python
    rejected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
```

Add a table-level unique constraint at the bottom of the class body:

```python
    __table_args__ = (
        sa.UniqueConstraint(
            "swap_request_id", "side", "commander_id", "approver_kind",
            name="uq_swap_manager_approval_request_side_person_kind",
        ),
    )
```

(Check the file's existing `import sqlalchemy as sa` alias at the top — reuse whatever alias is already used elsewhere in the file, e.g. `DutyManagerScope`'s `sa.UniqueConstraint` at line ~1029, for consistency.)

In `SwapRequest` (after the existing `decision_note` column):

```python
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
```

- [ ] **Step 2: Generate the migration**

Run: `alembic revision -m "swap approval decision log"`

- [ ] **Step 3: Write the migration body**

```python
"""swap approval decision log

Revision ID: <generated>
Revises: <previous_head>
Create Date: <generated>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "<generated>"
down_revision = "<previous_head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("swap_manager_approvals", sa.Column("rejected", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("swap_manager_approvals", sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("swap_manager_approvals", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_swap_manager_approvals_rejected_by_soldiers", "swap_manager_approvals", "soldiers",
        ["rejected_by"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_swap_manager_approval_request_side_person_kind", "swap_manager_approvals",
        ["swap_request_id", "side", "commander_id", "approver_kind"],
    )
    op.add_column("swap_requests", sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_swap_requests_rejected_by_soldiers", "swap_requests", "soldiers",
        ["rejected_by"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_swap_requests_rejected_by_soldiers", "swap_requests", type_="foreignkey")
    op.drop_column("swap_requests", "rejected_by")
    op.drop_constraint("uq_swap_manager_approval_request_side_person_kind", "swap_manager_approvals", type_="unique")
    op.drop_constraint("fk_swap_manager_approvals_rejected_by_soldiers", "swap_manager_approvals", type_="foreignkey")
    op.drop_column("swap_manager_approvals", "rejected_at")
    op.drop_column("swap_manager_approvals", "rejected_by")
    op.drop_column("swap_manager_approvals", "rejected")
```

Fill in `revision`/`down_revision`/`Revision ID`/`Revises`/`Create Date` with whatever `alembic revision` actually generated in Step 2 — do not hand-guess these values.

- [ ] **Step 4: Apply the migration**

Run: `alembic upgrade head`
Expected: succeeds with no errors.

- [ ] **Step 5: Verify by round-tripping the migration**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: both succeed cleanly (proves `downgrade()` is correct, not just `upgrade()`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add per-decision rejection columns to swap approval tables"
```

---

### Task 3: Swaps — decision log, live satisfaction check, generalized one-click resolution

**Files:**
- Modify: `backend/app/services/swaps.py` (multiple functions — see below)
- Test: `backend/app/services/tests/test_swaps.py`

**Interfaces:**
- Consumes: `commander_chain_for_soldier`, `duty_manager_chain_for_soldier` (Task 1)
- Produces: `approve_manager_row(session, *, request_id, actor_id) -> SwapRequest` (signature change — drops `side`/`commander_id` params), `_qualifying_rows_for_actor(session, req, actor_id) -> list[tuple[str, str]]`, `reject_manager_row(session, *, request_id, actor_id, decision_note=None) -> SwapRequest` (new) — consumed by Task 4 (routes) and Task 5.

- [ ] **Step 1: Delete `_create_manager_approval_rows` and its two call sites**

In `backend/app/services/swaps.py`:
- Delete the function body at lines 258-277 (`_create_manager_approval_rows`).
- Delete `duty_manager_ids` (lines 219-220) — it's now dead code, superseded by `duty_manager_chain_for_soldier`.
- In `claim_request` (around line 578), delete the line `_create_manager_approval_rows(session, req=req)`.
- In `cover_offer` (around line 830), delete the line `_create_manager_approval_rows(session, req=req)`.

- [ ] **Step 2: Write the failing tests for live satisfaction + generalized one-click resolution**

```python
def test_finalize_with_scoped_duty_manager_not_org_wide(admin_session):
    from app.db.models import DutyManagerScope
    from app.services.approval_scope import duty_manager_chain_for_soldier

    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    other_node = create_node(admin_session, level="unit", name=f"other_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number=f"cov_{_uid()}", hierarchy_node_id=node.id)
    in_scope_dm = create_soldier(admin_session, personal_number=f"in_dm_{_uid()}", role="duty_manager")
    out_of_scope_dm = create_soldier(admin_session, personal_number=f"out_dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=in_scope_dm.id, hierarchy_node_id=node.id))
    admin_session.add(DutyManagerScope(duty_manager_id=out_of_scope_dm.id, hierarchy_node_id=other_node.id))
    admin_session.commit()

    assert out_of_scope_dm.id not in duty_manager_chain_for_soldier(admin_session, soldier.id)
    assert in_scope_dm.id in duty_manager_chain_for_soldier(admin_session, soldier.id)


def test_one_click_approves_every_qualifying_row_across_sides_and_kinds(admin_session):
    """A person who is both the commander AND the (properly-scoped)
    duty-manager for BOTH the requester's and covering soldier's node needs
    exactly one approve_manager_row call to satisfy all four requirements."""
    from app.db.models import DutyManagerScope

    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    node.commander_id = None  # set after creating the dual-role person below
    requester = create_soldier(admin_session, personal_number=f"req_{_uid()}", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number=f"cov_{_uid()}", hierarchy_node_id=node.id)
    dual = create_soldier(admin_session, personal_number=f"dual_{_uid()}")
    node.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=node.id))
    admin_session.commit()

    assignment = _make_assignment(admin_session, soldier=requester, node=node)
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, covering_soldier_id=covering.id, status="pending_approval",
        requester_side_approved=True, covering_side_approved=True,
    )
    admin_session.add(req)
    admin_session.commit()

    from app.services.swaps import approve_manager_row, _all_approved

    approve_manager_row(admin_session, request_id=req.id, actor_id=dual.id)
    admin_session.commit()

    assert _all_approved(admin_session, req) is True
    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == req.id)
    ).scalars().all()
    # 2 sides x 2 kinds = 4 rows, all approved by the same dual-role person in one call
    assert len(rows) == 4
    assert all(r.approved and r.approved_by == dual.id for r in rows)


def test_stranger_still_cannot_approve(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    commander = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    node.commander_id = commander.id
    requester = create_soldier(admin_session, personal_number=f"r_{_uid()}", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number=f"str_{_uid()}")
    admin_session.commit()

    assignment = _make_assignment(admin_session, soldier=requester, node=node)
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="pending_approval",
        requester_side_approved=True, covering_side_approved=True,
    )
    admin_session.add(req)
    admin_session.commit()

    from app.services.swaps import approve_manager_row, SwapError
    with pytest.raises(SwapError, match="not_required_approver"):
        approve_manager_row(admin_session, request_id=req.id, actor_id=stranger.id)


def test_reject_manager_row_stamps_the_specific_row_then_kills_whole_request(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    commander = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    node.commander_id = commander.id
    requester = create_soldier(admin_session, personal_number=f"r_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()

    assignment = _make_assignment(admin_session, soldier=requester, node=node)
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="pending_approval",
        requester_side_approved=True, covering_side_approved=True,
    )
    admin_session.add(req)
    admin_session.commit()

    from app.services.swaps import reject_manager_row

    reject_manager_row(admin_session, request_id=req.id, actor_id=commander.id, decision_note="לא מתאים")
    admin_session.commit()
    admin_session.refresh(req)

    assert req.status == "rejected"
    assert req.rejected_by == commander.id
    row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id, SwapManagerApproval.commander_id == commander.id,
        )
    ).scalar_one()
    assert row.rejected is True
    assert row.rejected_by == commander.id


def test_claim_auto_approves_both_soldier_sides(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"r_{_uid()}", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number=f"cov_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()

    assignment = _make_assignment(admin_session, soldier=requester, node=node)
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    admin_session.add(req)
    admin_session.commit()

    from app.services.swaps import claim_request

    claim_request(admin_session, request_id=req.id, covering_soldier_id=covering.id)
    admin_session.commit()
    admin_session.refresh(req)

    assert req.requester_side_approved is True
    assert req.covering_side_approved is True
    assert req.status == "pending_approval"
```

(`_make_assignment` already exists in this test file at line 58 — reuse it.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest app/services/tests/test_swaps.py -k "scoped_duty_manager or one_click_approves or stranger_still or reject_manager_row or claim_auto_approves" -v`
Expected: FAIL — the new/generalized functions don't exist yet, and `claim_request` still resets the flags to `None`.

- [ ] **Step 4: Rewrite `_all_approved` for live computation**

Replace `_all_approved` (`swaps.py:280-309`):

```python
def _has_decision(session: Session, request_id: uuid.UUID, side: str, kind: str, *, approved: bool) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approver_kind == kind,
            SwapManagerApproval.approved == approved,  # noqa: E712
        ).limit(1)
    ).first() is not None


def _all_approved(session: Session, req: SwapRequest) -> bool:
    """Both soldiers must have approved (auto-set on claim/cover_offer), and
    — for each (side, kind) whose LIVE chain is non-empty — at least one
    approved decision-log row must exist for that (side, kind). A (side,
    kind) with an empty live chain (no commander at all, duty-manager
    approval off, or no duty manager currently in scope) is vacuously
    satisfied. Live chain membership only gates NEW clicks and what's
    displayed as required — a decision already recorded stays valid even if
    the org changes afterward."""
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    require_dm = _require_duty_manager_approval(session)
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            return False
        if commander_chain_for_soldier(session, soldier_id) and not _has_decision(session, req.id, side, "commander", approved=True):
            return False
        if require_dm and duty_manager_chain_for_soldier(session, soldier_id) and not _has_decision(session, req.id, side, "duty_manager", approved=True):
            return False
    return True
```

- [ ] **Step 5: Rewrite `is_chain_commander_for_side` for live computation**

Replace `swaps.py:357-372`:

```python
def is_chain_commander_for_side(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID
) -> bool:
    """Is `commander_id` CURRENTLY (live) a required commander-in-scope or
    duty-manager-in-scope for this side — regardless of whether they've
    already approved. Used to route between the chain-member path
    (approve_manager_row) and the broader-authorization override path
    (approve_manager_side_override)."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        return False
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        return False
    if commander_id in commander_chain_for_soldier(session, soldier_id):
        return True
    if _require_duty_manager_approval(session) and commander_id in duty_manager_chain_for_soldier(session, soldier_id):
        return True
    return False
```

- [ ] **Step 6: Rewrite `approve_manager_row` with generalized one-click resolution**

Replace `swaps.py:375-450` in full:

```python
def _qualifying_rows_for_actor(session: Session, req: SwapRequest, actor_id: uuid.UUID) -> list[tuple[str, str]]:
    """Every (side, kind) `actor_id` is CURRENTLY (live) a required approver
    for on this request — spans both sides and both kinds in one pass, so a
    single approve/reject call resolves everything this person is eligible
    for at once (same person commander of both soldiers, or duty-manager of
    both, or both roles for one or both soldiers — no special-casing)."""
    require_dm = _require_duty_manager_approval(session)
    out: list[tuple[str, str]] = []
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        if actor_id in commander_chain_for_soldier(session, soldier_id):
            out.append((side, "commander"))
        if require_dm and actor_id in duty_manager_chain_for_soldier(session, soldier_id):
            out.append((side, "duty_manager"))
    return out


def _get_or_create_row(session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID, kind: str) -> SwapManagerApproval:
    row = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == actor_id,
            SwapManagerApproval.approver_kind == kind,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SwapManagerApproval(swap_request_id=request_id, side=side, commander_id=actor_id, approver_kind=kind)
        session.add(row)
    return row


def approve_manager_row(session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID) -> SwapRequest:
    """Approve every (side, kind) row `actor_id` currently qualifies for on
    this request, in one call. Idempotent: rows already approved are left
    untouched (original approver/timestamp kept). Raises
    SwapError("not_required_approver") if `actor_id` doesn't currently
    qualify for anything on this request."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id)
    if not qualifying:
        raise SwapError("not_required_approver")
    now = datetime.utcnow()
    for side, kind in qualifying:
        row = _get_or_create_row(session, request_id=request_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            write_audit(
                session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
                entity_id=req.id, after={"side": side, "kind": kind},
            )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def reject_manager_row(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, decision_note: str | None = None,
) -> SwapRequest:
    """Stamp rejected on every (side, kind) row `actor_id` currently
    qualifies for on this request (if any), then kill the whole request via
    the existing reject_request path — same overall effect as today (any
    required approver rejecting still ends the swap immediately), now with
    per-row attribution for display. Permissive: if `actor_id` doesn't
    qualify for any specific row (e.g. a broader-authorization override
    actor, not a literal chain member), this simply skips row-stamping and
    still proceeds to reject_request — the route is responsible for having
    already authorized the caller before reaching this function."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    now = datetime.utcnow()
    for side, kind in _qualifying_rows_for_actor(session, req, actor_id):
        row = _get_or_create_row(session, request_id=request_id, side=side, actor_id=actor_id, kind=kind)
        if not row.rejected:
            row.rejected = True
            row.rejected_by = actor_id
            row.rejected_at = now
    session.flush()
    return reject_request(session, request_id=request_id, decision_note=decision_note, actor_id=actor_id)
```

- [ ] **Step 7: Rewrite `approve_manager_side_override` for the lazy model**

Replace `swaps.py:483-513` (the old version flips existing unapproved rows — under the lazy model, no rows are pre-populated, so it must now insert approved rows for every live-required kind on that side, attributed to the overriding actor):

```python
def approve_manager_side_override(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID
) -> SwapRequest:
    """Used when the acting user is authorized (admin / duty-manager / broader
    commander scope) but isn't literally one of the required chain
    commanders/duty-managers — inserts (or updates) an approved row for
    every LIVE-required kind on that side, attributed to actor_id, clearing
    the whole side's requirement at once."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        raise SwapError("no_soldier_for_side")
    kinds_needed = []
    if commander_chain_for_soldier(session, soldier_id):
        kinds_needed.append("commander")
    if _require_duty_manager_approval(session) and duty_manager_chain_for_soldier(session, soldier_id):
        kinds_needed.append("duty_manager")
    now = datetime.utcnow()
    cleared = 0
    for kind in kinds_needed:
        row = _get_or_create_row(session, request_id=request_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            cleared += 1
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve_override", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "rows_cleared": cleared},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req
```

- [ ] **Step 8: Update `approve_manager_side`'s call to `approve_manager_row`**

In `swaps.py:453-480`, change the call at line ~474 from
`approve_manager_row(session, request_id=request_id, side=side, commander_id=actor_id, actor_id=actor_id)`
to
`approve_manager_row(session, request_id=request_id, actor_id=actor_id)`
(the function no longer takes `side`/`commander_id` — it resolves everything live). No other change to `approve_manager_side`'s own signature or body.

- [ ] **Step 9: Auto-approve soldier side on claim/cover_offer**

In `claim_request` (`swaps.py`, in the `if _require_approval(session):` branch, ~line 576):
```python
# was: req.requester_side_approved = None; req.covering_side_approved = None
req.requester_side_approved = True   # asking already implied consent
req.covering_side_approved = True    # covering (claiming) already implied consent
```

In `cover_offer` (same file, ~line 828), identical change.

- [ ] **Step 10: Attribute rejection on `SwapRequest` itself**

In `reject_request` (`swaps.py:639-670`), add `req.rejected_by = actor_id` alongside the existing `req.status = "rejected"` / `req.decision_note = decision_note` lines, and include it in the `write_audit` `after` dict.

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest app/services/tests/test_swaps.py -v`
Expected: some pre-existing tests will now fail because they assert the OLD pre-populated-roster behavior — this is expected and addressed in Step 12.

- [ ] **Step 12: Update/remove obsolete pre-existing tests**

- `test_claim_creates_manager_approval_rows_for_both_chains` (line 159): this test's premise (rows exist immediately after claim, before anyone approves) is no longer true — rewrite it to assert that `SwapManagerApproval` rows do NOT exist yet immediately after claim (`session.execute(select(SwapManagerApproval).where(...)).scalars().all() == []`), proving the roster is no longer pre-populated.
- `test_finalize_requires_both_soldiers_and_all_managers` (line 172) and `test_finalize_with_no_commanders_needs_only_soldiers` (line 198): re-verify these still pass conceptually under live computation — likely need their soldier-approval setup adjusted since `claim_request`/`cover_offer` now auto-set the flags (if the test manually sets `requester_side_approved`/`covering_side_approved` after calling claim, that's now redundant but harmless; if it relied on them staying `None` after claim to test the "not both approved" path, rewrite that part to explicitly set one flag back to `None`/`False` after claiming, to still exercise the "not both approved" branch of `_all_approved`).
- `test_any_one_chain_commander_approval_suffices_for_side` (line 257), `test_same_commander_reapproving_is_a_harmless_noop` (line 286), `test_is_chain_commander_for_side_true_regardless_of_approval_state` (line 326), `test_stranger_is_not_a_chain_commander_and_cannot_approve` (line 338), `test_approve_manager_side_override_clears_all_rows_for_side` (line 354): re-run each individually and fix any call sites still passing the old `approve_manager_row(..., side=..., commander_id=...)` signature to the new `approve_manager_row(session, request_id=..., actor_id=...)`.

Run: `pytest app/services/tests/test_swaps.py -v`
Expected: PASS, all tests (new and updated).

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/swaps.py backend/app/services/tests/test_swaps.py
git commit -m "feat: replace pre-populated swap approval roster with live-computed decision log"
```

---

### Task 4: Swap routes — manager reject wiring, response serialization

**Files:**
- Modify: `backend/app/routes/swaps.py`
- Test: `backend/app/routes/tests/test_swaps_api.py` (find exact filename — likely under `backend/tests/integration/test_swaps_api.py` per `CLAUDE.md`'s test layout; verify with `find backend -iname "*swaps*"` before writing paths)

**Interfaces:**
- Consumes: `reject_manager_row` (Task 3)
- Produces: `SwapManagerApprovalOut` gains `rejected`/`rejected_by_name`/`rejected_at` — consumed by Task 6 (frontend)

- [ ] **Step 1: Locate the actual integration test file**

Run: `find backend -iname "*swaps*"` (from repo root) — use whatever path this reveals for the test file in the steps below; the plan assumes `backend/tests/integration/test_swaps_api.py` based on `CLAUDE.md`'s stated layout, but confirm before editing.

- [ ] **Step 2: Write the failing test for manager-reject row attribution**

```python
def test_manager_reject_records_rejecting_commander_on_row(client, admin_headers, ...):
    # Set up a swap in pending_approval with a real chain commander, call
    # POST /swaps/{id}/manager-reject as that commander, then GET the swap
    # and assert requester_manager_approvals (or covering_manager_approvals,
    # whichever side the commander belongs to) contains one row with
    # rejected=True and rejected_by_name == the commander's full_name, and
    # assert response status == "rejected" with SwapOut exposing the
    # rejecting commander's name somewhere reachable (decide exact field
    # name to add to SwapOut for "who rejected" during implementation —
    # e.g. `rejected_by_name: str | None` alongside the existing
    # `decision_note`).
    ...
```

(Write this against the actual existing test file's fixture conventions — read 2-3 existing tests in whichever file Step 1 located, to match its exact `client`/auth-header/seed-data helper style before finalizing this test's body.)

- [ ] **Step 3: Add `rejected`/`rejected_by_name`/`rejected_at` to `SwapManagerApprovalOut`, and `rejected_by_name` to `SwapOut`**

In `backend/app/routes/swaps.py`, extend `SwapManagerApprovalOut` (line 33-40):

```python
class SwapManagerApprovalOut(BaseModel):
    commander_id: uuid.UUID
    commander_name: str | None = None
    approved: bool
    approved_by: uuid.UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    rejected: bool = False
    rejected_by: uuid.UUID | None = None
    rejected_by_name: str | None = None
    rejected_at: datetime | None = None
    approver_kind: str
```

Extend `SwapOut` (line 43-71) with one new field after `decision_note`:

```python
    rejected_by_name: str | None = None
```

- [ ] **Step 4: Rewrite `_manager_approvals_out` to live-compute the roster and cross-reference existing decisions**

Replace `swaps.py:108-128`:

```python
def _manager_approvals_out(session: Session, request_id: uuid.UUID, soldier_id: uuid.UUID, side: str) -> list[SwapManagerApprovalOut]:
    from app.services.approval_scope import commander_chain_for_soldier, duty_manager_chain_for_soldier
    from app.services.swaps import _require_duty_manager_approval

    decisions_by_person_kind = {
        (row.commander_id, row.approver_kind): row
        for row in session.execute(
            select(SwapManagerApproval).where(
                SwapManagerApproval.swap_request_id == request_id,
                SwapManagerApproval.side == side,
            )
        ).scalars().all()
    }

    chains: list[tuple[str, uuid.UUID]] = [("commander", cid) for cid in commander_chain_for_soldier(session, soldier_id)]
    if _require_duty_manager_approval(session):
        chains += [("duty_manager", did) for did in duty_manager_chain_for_soldier(session, soldier_id)]

    out = []
    for kind, person_id in chains:
        row = decisions_by_person_kind.get((person_id, kind))
        person = session.get(Soldier, person_id)
        approved_by = session.get(Soldier, row.approved_by) if row and row.approved_by else None
        rejected_by = session.get(Soldier, row.rejected_by) if row and row.rejected_by else None
        out.append(SwapManagerApprovalOut(
            commander_id=person_id,
            commander_name=person.full_name if person else None,
            approved=bool(row.approved) if row else False,
            approved_by=row.approved_by if row else None,
            approved_by_name=approved_by.full_name if approved_by else None,
            approved_at=row.approved_at if row else None,
            rejected=bool(row.rejected) if row else False,
            rejected_by=row.rejected_by if row else None,
            rejected_by_name=rejected_by.full_name if rejected_by else None,
            rejected_at=row.rejected_at if row else None,
            approver_kind=kind,
        ))
    return out
```

Note the signature gained a `soldier_id` param (needed to compute the live chain — the old version only needed `request_id`/`side` since it just read persisted rows). Update its two call sites in `_out` (line ~183-184):

```python
    requester_manager_approvals = _manager_approvals_out(session, r.id, r.requesting_soldier_id, "requester") if session is not None and r.requesting_soldier_id else []
    covering_manager_approvals = _manager_approvals_out(session, r.id, r.covering_soldier_id, "covering") if session is not None and r.covering_soldier_id else []
```

- [ ] **Step 5: Simplify `_manager_approvals_out_bulk`**

The old bulk-optimization (`swaps.py:131-151`) pre-loaded `SwapManagerApproval` rows in bulk specifically to avoid N+1 queries against that table — under the live model, the expensive part shifts to hierarchy/`DutyManagerScope` lookups, a different shape of query entirely. Rather than preserve the old pre-loaded-dict signature, replace its body to simply delegate to `_manager_approvals_out` per request (accept the N+1 cost for now — this is a reasonable simplification, not a regression, since the old bulk path was optimizing a query pattern that no longer exists; note in the PR description that this is a candidate for a follow-up batch-optimization if a bulk swap-list endpoint's latency becomes a real problem):

```python
def _manager_approvals_out_bulk(
    approvals_by_request: dict[tuple[uuid.UUID, str], list[SwapManagerApproval]],
    approval_soldier_names: dict[uuid.UUID, str | None],
    request_id: uuid.UUID,
    side: str,
) -> list[SwapManagerApprovalOut]:
    raise NotImplementedError(
        "superseded by _manager_approvals_out (live computation) — find this "
        "function's caller and switch it to call _manager_approvals_out(session, "
        "request_id, soldier_id, side) directly; delete this function once no "
        "callers remain"
    )
```

Then find the actual caller (`grep -n "_manager_approvals_out_bulk" backend/app/routes/swaps.py`) and update it to call `_manager_approvals_out(session, request_id, soldier_id, side)` per request instead of using the pre-loaded-dicts path, removing whatever bulk-preload query built `approvals_by_request`/`approval_soldier_names` if nothing else consumes them afterward.

- [ ] **Step 6: Update `manager_reject` route to call `reject_manager_row`**

In `backend/app/routes/swaps.py`, `manager_reject` (line 760-788): replace the direct call to `svc.reject_request(...)` (line 783) with `svc.reject_manager_row(session, request_id=request_id, actor_id=user.id, decision_note=body.decision_note)` — the authorization check above it (looping over `req_node`/`cov_node` with `authorize(..., Action.SWAP_APPROVE, ...)`) stays exactly as-is; only the final service call changes.

- [ ] **Step 7: Run the test from Step 2, then the full swaps route test file**

Run: `pytest <path-found-in-step-1> -k "manager_reject" -v` then `pytest <path-found-in-step-1> -v`
Expected: PASS, all tests including any pre-existing ones exercising `manager-approve`/`manager-reject` (fix any that assumed the old pre-populated-roster shape of `requester_manager_approvals`/`covering_manager_approvals` in their assertions — the live-computed list will include EVERY live chain member now, not just ones with existing rows, which is more complete than before, not less).

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/swaps.py <test file path>
git commit -m "feat: live-compute swap manager approval roster in API responses, wire per-row rejection"
```

---

### Task 5: The other 4 request types — nearest commander/duty-manager display fields

**Files:**
- Modify: `backend/app/routes/exemption_requests.py`, `backend/app/routes/constraints.py`, `backend/app/routes/soldiers.py`, `backend/app/routes/enrollment.py`
- Test: existing test files for each route (find via `find backend -iname "*exemption_request*" -o -iname "*constraint*" -o -iname "*enrollment*"` under `backend/tests/`)

**Interfaces:**
- Consumes: `nearest_commander_for_soldier`, `nearest_duty_manager_for_soldier` (Task 1)
- Produces: `nearest_commander: {id, name} | None`, `nearest_duty_manager: {id, name} | None` on `ConstraintOut`, `ExemptionRequestOut`, `FieldUpdateOut`, `EnrollmentRequestOut` — consumed by Task 7 (frontend)

**No change to any `authorize()`/`Action` call, no change to approval-count/sequence logic in any of these 4 files — purely additive response fields.**

- [ ] **Step 1: Add a shared response sub-model**

In a shared location reachable by all 4 route files — check whether these files already share a common schemas module; if not, define this small model at the top of each of the 4 files (simplest, avoids a new shared-schema-module dependency for 4 small models):

```python
class NearestApproverOut(BaseModel):
    id: uuid.UUID
    name: str
```

- [ ] **Step 2: `ConstraintOut` (`backend/app/routes/constraints.py`)**

Add to `ConstraintOut` (line 23-35): `nearest_commander: NearestApproverOut | None = None` and `nearest_duty_manager: NearestApproverOut | None = None`.

Update `_out` (line 67-81) to accept and pass these through:

```python
def _out(
    c: PersonalConstraint, soldier_name: str = "", node_name: str | None = None, include_reason: bool = True,
    nearest_commander: NearestApproverOut | None = None, nearest_duty_manager: NearestApproverOut | None = None,
) -> ConstraintOut:
    return ConstraintOut(
        id=c.id, soldier_id=c.soldier_id, soldier_name=soldier_name, node_name=node_name,
        start_date=c.start_date, end_date=c.end_date, reason=c.reason if include_reason else None,
        status=c.status, decided_by=c.decided_by, decided_at=c.decided_at, decision_note=c.decision_note,
        created_at=c.created_at, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager,
    )


def _nearest_approvers(session: Session, soldier_id: uuid.UUID) -> tuple[NearestApproverOut | None, NearestApproverOut | None]:
    from app.services.approval_scope import nearest_commander_for_soldier, nearest_duty_manager_for_soldier
    cmd_id = nearest_commander_for_soldier(session, soldier_id)
    dm_id = nearest_duty_manager_for_soldier(session, soldier_id)
    cmd = session.get(Soldier, cmd_id) if cmd_id else None
    dm = session.get(Soldier, dm_id) if dm_id else None
    return (
        NearestApproverOut(id=cmd.id, name=cmd.full_name) if cmd else None,
        NearestApproverOut(id=dm.id, name=dm.full_name) if dm else None,
    )
```

Find every call site that constructs a `_out(...)` for a constraint whose `soldier_id` is known (the list/detail endpoints — `grep -n "_out(" backend/app/routes/constraints.py`) and pass `nearest_commander, nearest_duty_manager = _nearest_approvers(session, c.soldier_id)` then thread them into the `_out(...)` call.

- [ ] **Step 3: `ExemptionRequestOut` (`backend/app/routes/exemption_requests.py`)**

Same pattern: add the two fields to `ExemptionRequestOut` (line 38-...), extend its `_out` (line 82-...) the same way, add the same `_nearest_approvers` helper (or import a shared one if Step 1's model was centralized), thread through every call site.

- [ ] **Step 4: `FieldUpdateOut` (`backend/app/routes/soldiers.py`)**

Same pattern for `FieldUpdateOut` (line 114-...).

- [ ] **Step 5: `EnrollmentRequestOut` (`backend/app/routes/enrollment.py`)**

Same pattern for `EnrollmentRequestOut` (line 29-...).

- [ ] **Step 6: Write one test per type proving the new fields are populated correctly**

For each of the 4 files, add one test to its existing route test file following that file's existing fixture conventions:

```python
def test_constraint_list_includes_nearest_commander_and_duty_manager(client, ...):
    # seed a soldier under a node with a commander and an in-scope duty
    # manager, create a pending PersonalConstraint for that soldier, GET the
    # relevant list endpoint, assert the returned item's nearest_commander.id
    # and nearest_duty_manager.id match the seeded commander/duty-manager.
    ...
```//
(Mirror the exact seeding/assertion style of an existing neighboring test in
each file — read one before writing this, to match helper usage precisely.)

- [ ] **Step 7: Run each of the 4 route test files**

Run: `pytest <exemption_requests test file> <constraints test file> <soldiers field-update test file> <enrollment test file> -v`
Expected: PASS

- [ ] **Step 8: Run the full backend suite for regressions**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/exemption_requests.py backend/app/routes/constraints.py backend/app/routes/soldiers.py backend/app/routes/enrollment.py <4 test files>
git commit -m "feat: expose nearest commander/duty-manager on exemption/constraint/field-update/enrollment responses"
```

---

### Task 6: Frontend — rejected state on `DirectCommanderApproval`

**Files:**
- Modify: `frontend/src/components/DirectCommanderApproval.tsx`
- Modify: `frontend/src/api/swaps.ts` (extend the `SwapManagerApproval`-equivalent TS type with the 4 new fields from Task 4)

**Interfaces:**
- Consumes: `rejected`/`rejected_by_name`/`rejected_at` fields from `SwapManagerApprovalOut` (Task 4)
- Produces: `DirectCommanderApprovalRow` gains `rejected`/`rejected_by_name` — consumed by Task 7

- [ ] **Step 1: Extend the TS type in `api/swaps.ts`**

Find the interface mirroring `SwapManagerApprovalOut` (likely named `SwapManagerApproval` or similar — `grep -n "approver_kind" frontend/src/api/swaps.ts`) and add:

```ts
rejected: boolean;
rejected_by: string | null;
rejected_by_name: string | null;
rejected_at: string | null;
```

- [ ] **Step 2: Extend `DirectCommanderApprovalRow` and `ApprovalDot`**

In `frontend/src/components/DirectCommanderApproval.tsx`:

```tsx
export interface DirectCommanderApprovalRow {
  commander_id: string;
  commander_name?: string | null;
  approved: boolean;
  approved_by_name?: string | null;
  rejected?: boolean;
  rejected_by_name?: string | null;
  approver_kind?: "commander" | "duty_manager";
}
```

Update `ApprovalDot` usage in the component body: where it currently computes `satisfied ? true : null` for the dot value, change to a three-way: if any row is rejected, pass `false` (renders ✗); else if satisfied, pass `true`; else `null`. Add a note (mirroring the existing `approvedByOther` note) naming who rejected, when applicable:

```tsx
  const rejectedRow = approvals.find((a) => a.rejected);
  const dotValue = rejectedRow ? false : satisfied ? true : null;
  // ...
  <ApprovalDot value={dotValue} />
  {rejectedRow && (
    <span className="text-red-500 text-xs">
      {t("swaps.rejected_by", { name: rejectedRow.rejected_by_name ?? rejectedRow.commander_name ?? rejectedRow.commander_id.slice(0, 8) })}
    </span>
  )}
```

Add the `swaps.rejected_by` translation key to the Hebrew locale file (`frontend/src/locales/he/*.json` or wherever `swaps.approved_by_other` currently lives — check that file, add the sibling key with matching style, e.g. `"rejected_by": "נדחה ע\"י {{name}}"`).

- [ ] **Step 3: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: no new errors.

- [ ] **Step 4: Manual verification**

Start the dev stack, get a swap into `pending_approval`, reject it as a chain commander, confirm the ✗ + rejected-by note renders on the correct side/kind.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DirectCommanderApproval.tsx frontend/src/api/swaps.ts frontend/src/locales
git commit -m "feat: show per-row rejection attribution in swap approval status"
```

---

### Task 7: Frontend — wire `nearest_commander`/`nearest_duty_manager` into the other 4 types' cards

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/src/api/constraints.ts`, `frontend/src/api/exemptions.ts`, `frontend/src/api/soldiers.ts`, `frontend/src/api/enrollment.ts` (TS types for the new fields)

**Interfaces:**
- Consumes: `nearest_commander`/`nearest_duty_manager` (Task 5), `DirectCommanderApproval`+`groupByKind` (existing component, extended in Task 6)

- [ ] **Step 1: Extend the 4 TS DTOs**

In each of `api/constraints.ts`/`api/exemptions.ts`/`api/soldiers.ts` (the `FieldUpdateDTO` type)/`api/enrollment.ts`, add:

```ts
nearest_commander: { id: string; name: string } | null;
nearest_duty_manager: { id: string; name: string } | null;
```

- [ ] **Step 2: Build a small helper to adapt these into `DirectCommanderApprovalRow[]`**

In `frontend/src/pages/ApprovalsPage.tsx`, add:

```tsx
function nearestApproversToRows(
  nearestCommander: { id: string; name: string } | null,
  nearestDutyManager: { id: string; name: string } | null,
  status: "pending" | "approved" | "rejected",
): DirectCommanderApprovalRow[] {
  const rows: DirectCommanderApprovalRow[] = [];
  if (nearestCommander) {
    rows.push({
      commander_id: nearestCommander.id, commander_name: nearestCommander.name,
      approved: status === "approved", rejected: status === "rejected", approver_kind: "commander",
    });
  }
  if (nearestDutyManager) {
    rows.push({
      commander_id: nearestDutyManager.id, commander_name: nearestDutyManager.name,
      approved: status === "approved", rejected: status === "rejected", approver_kind: "duty_manager",
    });
  }
  return rows;
}
```

(This reflects the existing single-decider model faithfully: since only ONE decision total is needed/recorded for these types, both the commander and duty-manager display rows share the same overall `status` — there's no independent per-kind approval state for these 4 types, matching "no policy change." The rows exist purely so `DirectCommanderApproval`/`groupByKind` can render "who's the relevant commander/DM" with a consistent status icon, not to imply two independent gates the way swaps has.)

- [ ] **Step 3: Render in each of the 4 tabs**

In each of the constraints/exemptions/field_updates/enrollment tab renderers within `ApprovalsPage.tsx`, add, alongside the existing status/approve/reject UI for each row:

```tsx
const approvalRows = nearestApproversToRows(item.nearest_commander, item.nearest_duty_manager, item.status === "approved" ? "approved" : item.status === "rejected" ? "rejected" : "pending");
const grouped = groupByKind(approvalRows as (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]);
// ...
{grouped.commander.length > 0 && <span>{t("swaps.approver_kind_commander")}: <DirectCommanderApproval approvals={grouped.commander} /></span>}
{grouped.duty_manager.length > 0 && <span>{t("swaps.approver_kind_duty_manager")}: <DirectCommanderApproval approvals={grouped.duty_manager} /></span>}
```

(Reuse the existing `swaps.approver_kind_commander`/`swaps.approver_kind_duty_manager` translation keys — no new i18n needed here, matching the design's "similar UI" goal.)

Import `DirectCommanderApproval`, `groupByKind`, and its row type into `ApprovalsPage.tsx` at the top of the file alongside its existing imports.

- [ ] **Step 4: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 5: Manual verification**

Start the dev stack, open ApprovalsPage, confirm each of the 4 tabs (constraints/exemptions/field_updates/enrollment) shows the relevant commander/duty-manager name (clickable to profile via the existing `SoldierLink` inside `DirectCommanderApproval`) with a status dot.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/api/constraints.ts frontend/src/api/exemptions.ts frontend/src/api/soldiers.ts frontend/src/api/enrollment.ts
git commit -m "feat: show nearest commander/duty-manager on constraint/exemption/field-update/enrollment approval cards"
```

---

## Final Check

- [ ] Run the full backend suite: `pytest -q` (venv active)
- [ ] Run `pytest --slow -q` for the full suite including large-scale tests, since this touches core assignment/scoring-adjacent scaffolding (swap finalization creates `DutyDayOverride` rows) — confirm no CP-SAT-adjacent regressions
- [ ] Run `npm run lint` and `npm run typecheck` (frontend)
- [ ] Manually walk through: create a swap request, claim it, confirm both soldier-side flags are already true with no separate approve click needed; approve as the direct commander, confirm it finalizes if no duty-manager is required, or still shows pending duty-manager if required; reject as a chain member, confirm the specific row + the whole request show the rejecting person's name; confirm a person who is commander of both soldiers needs only one click.
