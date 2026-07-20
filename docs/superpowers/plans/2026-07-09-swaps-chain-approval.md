# Swaps Chain-of-Command Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix swaps so they actually apply, and so the soldier being asked to cover (and the requester) can genuinely approve/decline — with the swap finalizing only once both soldiers and every commander in both soldiers' chains of command have approved.

**Architecture:** `SwapRequest.requester_side_approved`/`covering_side_approved` are repurposed to mean "this soldier approved their own side" (soldiers act on these themselves now, not managers). A new `swap_manager_approvals` table holds one row per required commander per side, populated by walking `HierarchyNode.path_ids` for that side's soldier and collecting every distinct `commander_id` up to the root. The swap only applies once both soldier flags are true and every manager-approval row is approved. New endpoints let a soldier approve/reject their own side, and let a commander (or an admin/duty-manager override) approve/reject a side's manager requirement.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest (backend); React, TypeScript (frontend).

## Global Constraints

- Only applies to the `pending_approval` flow (`claim_request`, `cover_offer`). `take_free` (proactively taking another soldier's shift) is unchanged — it still applies immediately with no approval step, per existing `swaps.require_manager_approval` semantics for that action.
- When `swaps.require_manager_approval` is `false`, behavior for `claim_request`/`cover_offer` is unchanged (immediate apply, no soldier or manager approval rows at all).
- If a soldier has no commander anywhere in their hierarchy chain, that side's manager requirement is trivially satisfied (zero rows created for that side).
- Sending a notification to commanders when a swap enters `pending_approval` is out of scope for this plan — managers already discover pending swaps via the existing `/swaps/pending` list.
- A commander who appears in both sides' chains gets two independent approval rows (one per side) — no dedup.

---

### Task 1: `swap_manager_approvals` table

**Files:**
- Modify: `backend/app/db/models.py` (add `SwapManagerApproval`, after `SwapRequest` at line 510)
- Create: `backend/alembic/versions/<new_revision>_add_swap_manager_approvals.py`
- Test: `backend/app/services/tests/test_swaps.py` (or the existing swaps test file if one already exists — check with `ls backend/app/services/tests/test_swap*.py` first and append there instead of creating a duplicate)

**Interfaces:**
- Produces: `SwapManagerApproval` model with columns `id, swap_request_id, side, commander_id, approved, approved_by, approved_at, decision_note, created_at`.

- [ ] **Step 1: Add the model**

In `backend/app/db/models.py`, insert immediately after the `SwapRequest` class (after line 509, before `class PersonalConstraint`):

```python
class SwapManagerApproval(Base):
    __tablename__ = "swap_manager_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    swap_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_requests.id", ondelete="CASCADE")
    )
    # "requester" | "covering" — which side of the swap this approval belongs to.
    side: Mapped[str] = mapped_column(Text)
    # The commander whose chain-of-command approval this row represents.
    commander_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    approved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    # May differ from commander_id when an admin/duty-manager approves on the
    # required commander's behalf (broader-scope override).
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Generate and fill in the migration**

Run: `cd backend && alembic heads` to get the current head revision id (verify it's still `3dd30881eefd`; if not, use whatever it reports).

Run: `cd backend && alembic revision -m "add_swap_manager_approvals"` — this creates a new file under `backend/alembic/versions/`. Open it and replace the body with:

```python
"""add_swap_manager_approvals

Revision ID: <the generated id>
Revises: 3dd30881eefd
Create Date: <generated>

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "<the generated id>"
down_revision: Union[str, Sequence[str], None] = "3dd30881eefd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "swap_manager_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("swap_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("swap_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("commander_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_swap_manager_approvals_swap_request_id",
        "swap_manager_approvals",
        ["swap_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_swap_manager_approvals_swap_request_id", table_name="swap_manager_approvals")
    op.drop_table("swap_manager_approvals")
```

- [ ] **Step 3: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: no errors; `swap_manager_approvals` table exists (verify with `psql` or by running the test in Step 4).

- [ ] **Step 4: Write and run a smoke test for the model**

Append to the swaps service test file (find it first: `ls backend/app/services/tests/ | grep -i swap`; if none exists, create `backend/app/services/tests/test_swaps.py` with the header shown below):

```python
from __future__ import annotations

import uuid

from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_swap_manager_approval_row_can_be_created(admin_session):
    from app.db.models import DutyAssignment, DutyType, SwapManagerApproval, SwapRequest
    from datetime import date, timedelta

    node = create_node(admin_session, level="unit", name=f"smoke_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"sm_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"cm_{_uid()}")
    dt = DutyType(name=f"dt_{_uid()}", hierarchy_node_id=node.id)
    admin_session.add(dt)
    admin_session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=soldier.id, status="open",
    )
    admin_session.add(req)
    admin_session.flush()

    row = SwapManagerApproval(swap_request_id=req.id, side="requester", commander_id=commander.id)
    admin_session.add(row)
    admin_session.commit()
    admin_session.refresh(row)

    assert row.approved is False
    assert row.approved_by is None
```

Run: `cd backend && pytest app/services/tests/test_swaps.py -v`
Expected: passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/ backend/app/services/tests/test_swaps.py
git commit -m "feat: add swap_manager_approvals table"
```

---

### Task 2: Service layer — chain-of-command approval logic

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/app/services/tests/test_swaps.py`

**Interfaces:**
- Consumes: `SwapManagerApproval` from Task 1.
- Produces (all in `app.services.swaps`):
  - `commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]`
  - `approve_soldier_side(session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> SwapRequest`
  - `approve_manager_row(session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID, actor_id: uuid.UUID) -> SwapRequest`
  - `approve_manager_side_override(session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID) -> SwapRequest`
  - `has_required_manager_row(session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID) -> bool`
  - Existing `reject_request` is reused unchanged for both soldier- and manager-initiated rejection (it already just moves status to `rejected` — no side-specific logic needed since rejection kills the whole swap).
  - `claim_request` and `cover_offer` are modified to call a new private `_create_manager_approval_rows` when moving to `pending_approval`.
  - The old `approve_side(session, *, request_id, side, actor_id)` function is **removed** — replaced by `approve_soldier_side` and `approve_manager_row`/`approve_manager_side_override`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/services/tests/test_swaps.py`:

```python
from datetime import date, timedelta

import pytest

from app.db.models import DutyAssignment, DutyType, HierarchyNode, SwapManagerApproval, SwapRequest


def _make_assignment(session, *, soldier, node):
    dt = DutyType(name=f"dt_{_uid()}", hierarchy_node_id=node.id)
    session.add(dt)
    session.flush()
    a = DutyAssignment(
        duty_type_id=dt.id, soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_commander_chain_walks_to_root(admin_session):
    from app.services.swaps import commander_chain_for_soldier

    root = create_node(admin_session, level="division", name=f"root_{_uid()}")
    root_cmd = create_soldier(admin_session, personal_number=f"rc_{_uid()}", role="commander")
    root.commander_id = root_cmd.id
    mid = create_node(admin_session, level="unit", name=f"mid_{_uid()}", parent=root)
    mid_cmd = create_soldier(admin_session, personal_number=f"mc_{_uid()}", role="commander")
    mid.commander_id = mid_cmd.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=mid.id)

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert chain == [mid_cmd.id, root_cmd.id] or chain == [root_cmd.id, mid_cmd.id]
    assert set(chain) == {mid_cmd.id, root_cmd.id}


def test_commander_chain_excludes_soldier_commanding_own_node(admin_session):
    from app.services.swaps import commander_chain_for_soldier

    node = create_node(admin_session, level="unit", name=f"self_cmd_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id, role="commander")
    node.commander_id = soldier.id
    admin_session.commit()

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert soldier.id not in chain


def test_commander_chain_empty_when_no_commanders(admin_session):
    from app.services.swaps import commander_chain_for_soldier

    node = create_node(admin_session, level="unit", name=f"no_cmd_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert chain == []


def _setup_pending_swap(session, *, with_commanders: bool):
    node = create_node(session, level="unit", name=f"pend_{_uid()}")
    requester_cmd = create_soldier(session, personal_number=f"rcmd_{_uid()}", role="commander")
    covering_cmd = create_soldier(session, personal_number=f"ccmd_{_uid()}", role="commander")
    if with_commanders:
        node.commander_id = requester_cmd.id
    session.commit()
    requester = create_soldier(session, personal_number=f"req_{_uid()}", hierarchy_node_id=node.id)
    node2 = create_node(session, level="unit", name=f"pend2_{_uid()}")
    if with_commanders:
        node2.commander_id = covering_cmd.id
        session.commit()
    covering = create_soldier(session, personal_number=f"cov_{_uid()}", hierarchy_node_id=node2.id)
    assignment = _make_assignment(session, soldier=requester, node=node)

    from app.services.swaps import claim_request
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    session.add(req)
    session.commit()
    req = claim_request(session, request_id=req.id, covering_soldier_id=covering.id)
    session.commit()
    return req, requester, covering, requester_cmd, covering_cmd


def test_claim_creates_manager_approval_rows_for_both_chains(admin_session):
    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)

    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == req.id)
    ).scalars().all()
    by_side = {"requester": [], "covering": []}
    for r in rows:
        by_side[r.side].append(r.commander_id)
    assert by_side["requester"] == [requester_cmd.id]
    assert by_side["covering"] == [covering_cmd.id]


def test_finalize_requires_both_soldiers_and_all_managers(admin_session):
    from app.services.swaps import approve_soldier_side, approve_manager_row

    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"  # managers haven't approved yet

    approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=requester_cmd.id, actor_id=requester_cmd.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"  # covering-side manager still pending

    approve_manager_row(admin_session, request_id=req.id, side="covering", commander_id=covering_cmd.id, actor_id=covering_cmd.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"


def test_finalize_with_no_commanders_needs_only_soldiers(admin_session):
    from app.services.swaps import approve_soldier_side

    req, requester, covering, _, _ = _setup_pending_swap(admin_session, with_commanders=False)

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    admin_session.commit()
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"


def test_approve_soldier_side_rejects_non_party(admin_session):
    from app.services.swaps import approve_soldier_side, SwapError

    req, requester, covering, _, _ = _setup_pending_swap(admin_session, with_commanders=False)
    stranger = create_soldier(admin_session, personal_number=f"str_{_uid()}")

    with pytest.raises(SwapError, match="not_a_party"):
        approve_soldier_side(admin_session, request_id=req.id, soldier_id=stranger.id)


def test_approve_manager_row_rejects_wrong_commander(admin_session):
    from app.services.swaps import approve_manager_row, SwapError

    req, *_rest = _setup_pending_swap(admin_session, with_commanders=True)
    stranger = create_soldier(admin_session, personal_number=f"str2_{_uid()}")

    with pytest.raises(SwapError, match="not_required_approver"):
        approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=stranger.id, actor_id=stranger.id)


def test_approve_manager_side_override_clears_all_rows_for_side(admin_session):
    from app.services.swaps import approve_manager_side_override, approve_soldier_side

    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()

    approve_manager_side_override(admin_session, request_id=req.id, side="requester", actor_id=admin.id)
    admin_session.commit()
    row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id, SwapManagerApproval.side == "requester"
        )
    ).scalar_one()
    assert row.approved is True
    assert row.approved_by == admin.id

    approve_manager_side_override(admin_session, request_id=req.id, side="covering", actor_id=admin.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"
```

Add `from sqlalchemy import select` to the top-of-file imports of `backend/app/services/tests/test_swaps.py` (alongside the existing `from tests.helpers import ...` line) so the test above can query `SwapManagerApproval` rows directly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_swaps.py -v`
Expected: FAIL — `ImportError` for `commander_chain_for_soldier`, `approve_soldier_side`, `approve_manager_row`, `approve_manager_side_override` (none exist yet).

- [ ] **Step 3: Implement the service layer**

In `backend/app/services/swaps.py`, add the import and new functions. Update the top imports:

```python
from app.db.models import DutyAssignment, HierarchyNode, NotificationType, Soldier, SwapManagerApproval, SwapRequest
```

Add after `_require_approval`:

```python
def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct commander from the soldier's own node up to the root of
    the hierarchy, excluding the soldier themself if they command their own node."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for n in nodes:
        if n.commander_id and n.commander_id != soldier_id and n.commander_id not in seen:
            seen.add(n.commander_id)
            chain.append(n.commander_id)
    return chain


def _create_manager_approval_rows(session: Session, *, req: SwapRequest) -> None:
    """Populate swap_manager_approvals for both sides. Called once, when a swap
    enters pending_approval with a known covering soldier."""
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        for commander_id in commander_chain_for_soldier(session, soldier_id):
            session.add(SwapManagerApproval(swap_request_id=req.id, side=side, commander_id=commander_id))
    session.flush()


def _all_approved(session: Session, req: SwapRequest) -> bool:
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    pending = session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == req.id,
            SwapManagerApproval.approved == False,  # noqa: E712
        ).limit(1)
    ).first()
    return pending is None


def _try_finalize(session: Session, req: SwapRequest, actor_id: uuid.UUID | None) -> None:
    if not _all_approved(session, req):
        return
    _apply_cover(session, req=req, actor_id=actor_id)
    create_notification(session, soldier_id=req.requesting_soldier_id,
                        type=NotificationType.swap_accepted,
                        title="בקשת ההחלפה אושרה",
                        reference_type="swap_request", reference_id=req.id,
                        actor_id=actor_id)
    if req.covering_soldier_id:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה אושרה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="swap.apply", entity_type="swap_request",
        entity_id=req.id, after={"status": "applied"},
    )


def approve_soldier_side(
    session: Session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    if soldier_id == req.requesting_soldier_id:
        req.requester_side_approved = True
    elif soldier_id == req.covering_soldier_id:
        req.covering_side_approved = True
    else:
        raise SwapError("not_a_party")
    write_audit(
        session, actor_id=actor_id or soldier_id, action="swap.soldier_approve",
        entity_type="swap_request", entity_id=req.id, after={"soldier_id": str(soldier_id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id or soldier_id)
    session.flush()
    return req


def has_required_manager_row(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID
) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == commander_id,
            SwapManagerApproval.approved == False,  # noqa: E712
        )
    ).first() is not None


def approve_manager_row(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID, actor_id: uuid.UUID
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    row = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == commander_id,
            SwapManagerApproval.approved == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        raise SwapError("not_required_approver")
    row.approved = True
    row.approved_by = actor_id
    row.approved_at = datetime.utcnow()
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "commander_id": str(commander_id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def approve_manager_side_override(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID
) -> SwapRequest:
    """Used when the acting user is authorized (admin / duty-manager / broader
    commander scope) but isn't literally one of the required chain commanders —
    clears every outstanding row for that side at once."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    rows = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approved == False,  # noqa: E712
        )
    ).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.approved = True
        row.approved_by = actor_id
        row.approved_at = now
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve_override", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "rows_cleared": len(rows)},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req
```

Add `from datetime import date, timedelta, datetime` — the file currently has `from datetime import date, timedelta`, extend it to also import `datetime`.

Remove the old `approve_side` function entirely (it's fully superseded).

In `claim_request`, replace the `if _require_approval(session):` block's body (the part that sets `req.status = "pending_approval"` etc.) by adding a call to `_create_manager_approval_rows(session, req=req)` right after `req.status = "pending_approval"` and the two `None` resets. Same edit in `cover_offer`'s equivalent block. Both functions keep their existing notification/write_audit calls unchanged — only add the one new line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_swaps.py -v`
Expected: all passed

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest -q`
Expected: no failures other than any pre-existing tests that directly called the now-removed `approve_side` — those are addressed in Task 3 (routes) since they test through the API layer, not this function directly. If any *service-level* test still references `svc.approve_side`, update it now to use `approve_soldier_side`/`approve_manager_row` per the new semantics before moving on.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/swaps.py backend/app/services/tests/test_swaps.py
git commit -m "feat: chain-of-command manager approval for swaps"
```

---

### Task 3: Routes and schema

**Files:**
- Modify: `backend/app/routes/swaps.py`
- Test: `backend/tests/integration/test_swaps_api.py` (new)

**Interfaces:**
- Produces: `SwapManagerApprovalOut` schema; `SwapOut.requester_manager_approvals: list[SwapManagerApprovalOut]`, `SwapOut.covering_manager_approvals: list[SwapManagerApprovalOut]`; endpoints `POST /me/swaps/{request_id}/approve`, `POST /me/swaps/{request_id}/reject`, `POST /swaps/{request_id}/manager-approve`, `POST /swaps/{request_id}/manager-reject`. Removes `POST /swaps/{request_id}/approve` and `POST /swaps/{request_id}/reject` (replaced by the four above).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_swaps_api.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyType, SwapManagerApproval, SwapRequest
from tests.helpers import auth_headers, create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _setup(session: Session):
    """Build a requester + covering soldier, each under their own commander,
    and a pending_approval swap between them (via claim)."""
    req_node = create_node(session, level="unit", name=f"api_req_{_uid()}")
    cov_node = create_node(session, level="unit", name=f"api_cov_{_uid()}")
    req_cmd = create_soldier(session, personal_number=f"api_rc_{_uid()}", role="commander")
    cov_cmd = create_soldier(session, personal_number=f"api_cc_{_uid()}", role="commander")
    req_node.commander_id = req_cmd.id
    cov_node.commander_id = cov_cmd.id
    session.commit()

    requester = create_soldier(session, personal_number=f"api_req_s_{_uid()}", hierarchy_node_id=req_node.id)
    covering = create_soldier(session, personal_number=f"api_cov_s_{_uid()}", hierarchy_node_id=cov_node.id)

    dt = DutyType(name=f"api_dt_{_uid()}", hierarchy_node_id=req_node.id)
    session.add(dt)
    session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, soldier_id=requester.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    session.add(assignment)
    session.flush()

    swap_req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    session.add(swap_req)
    session.commit()

    return requester, covering, req_cmd, cov_cmd, assignment, swap_req


def test_soldier_can_approve_own_side(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    assert r.status_code == 200, r.text
    assert r.json()["requester_side_approved"] is True
    assert r.json()["status"] == "pending_approval"


def test_non_party_soldier_cannot_approve(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    stranger = create_soldier(admin_session, personal_number=f"api_str_{_uid()}")

    r = client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(stranger))
    assert r.status_code == 400


def test_full_approval_chain_applies_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(covering))
    client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(req_cmd), json={"side": "requester"})
    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd), json={"side": "covering"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"


def test_wrong_commander_cannot_manager_approve(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd), json={"side": "requester"})
    assert r.status_code == 403


def test_admin_override_clears_manager_side(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    admin = create_soldier(admin_session, personal_number=f"api_adm_{_uid()}", role="admin")

    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(admin), json={"side": "requester"})
    assert r.status_code == 200, r.text
    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id, SwapManagerApproval.side == "requester"
        )
    ).scalars().all()
    assert all(row.approved for row in rows)
    assert all(row.approved_by == admin.id for row in rows)


def test_swap_out_includes_manager_approvals(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.get("/api/me/swaps", headers=auth_headers(requester))
    assert r.status_code == 200
    swap_out = next(s for s in r.json() if s["id"] == str(swap_req.id))
    assert len(swap_out["requester_manager_approvals"]) == 1
    assert swap_out["requester_manager_approvals"][0]["commander_id"] == str(req_cmd.id)
    assert swap_out["requester_manager_approvals"][0]["approved"] is False
    assert len(swap_out["covering_manager_approvals"]) == 1


def test_soldier_reject_kills_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/reject", headers=auth_headers(covering), json={"decision_note": "no thanks"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_manager_reject_kills_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(req_cmd), json={"decision_note": "denied"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_swaps_api.py -v`
Expected: FAIL — the new routes (`/me/swaps/{id}/approve`, `/me/swaps/{id}/reject`, `/swaps/{id}/manager-approve`, `/swaps/{id}/manager-reject`) don't exist yet (404s).

- [ ] **Step 3: Implement the schema and routes**

In `backend/app/routes/swaps.py`:

1. Update the import line 11 to also bring in `Action, authorize, can, is_commander, is_duty_manager, scope_root_ids` (already there) — no change needed there. Update line 13's model import to include `SwapManagerApproval`:

```python
from app.db.models import DutyAssignment, DutyLocation, DutyType, HierarchyNode, SwapManagerApproval, SwapRequest, Soldier
```

2. Add a new schema class near `SwapOut` (before it, so `SwapOut` can reference it):

```python
class SwapManagerApprovalOut(BaseModel):
    commander_id: uuid.UUID
    commander_name: str | None = None
    approved: bool
    approved_by: uuid.UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
```

3. Add two fields to `SwapOut` (after `requesting_soldier_node_name`):

```python
    requester_manager_approvals: list[SwapManagerApprovalOut] = []
    covering_manager_approvals: list[SwapManagerApprovalOut] = []
```

4. Add a helper to build these lists, placed right after `_soldier_names`:

```python
def _manager_approvals_out(session: Session, request_id: uuid.UUID, side: str) -> list[SwapManagerApprovalOut]:
    rows = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
        )
    ).scalars().all()
    out = []
    for row in rows:
        commander = session.get(Soldier, row.commander_id)
        approved_by = session.get(Soldier, row.approved_by) if row.approved_by else None
        out.append(SwapManagerApprovalOut(
            commander_id=row.commander_id,
            commander_name=commander.full_name if commander else None,
            approved=row.approved,
            approved_by=row.approved_by,
            approved_by_name=approved_by.full_name if approved_by else None,
            approved_at=row.approved_at,
        ))
    return out
```

5. In `_out(...)`, add before the final `return SwapOut(...)`:

```python
    requester_manager_approvals = _manager_approvals_out(session, r.id, "requester") if session is not None else []
    covering_manager_approvals = _manager_approvals_out(session, r.id, "covering") if session is not None else []
```

and add `requester_manager_approvals=requester_manager_approvals, covering_manager_approvals=covering_manager_approvals,` to the `SwapOut(...)` constructor call.

6. In `_out_bulk(...)`, add a `session: Session` parameter (it currently takes none) and do the same — since `_out_bulk` is only called from `pending()`, update that call site too:

```python
def _out_bulk(
    session: Session,
    r: SwapRequest,
    soldiers: dict,
    nodes: dict,
    assignments: dict,
    duty_types: dict,
    duty_locations: dict,
    warnings: list[str] | None = None,
) -> SwapOut:
```

Add the same two lines as in `_out` right before its `return SwapOut(...)`, and add `requester_manager_approvals=..., covering_manager_approvals=...,` to that constructor call. Update both call sites (`return [_out_bulk(r, ...) for r in all_pending]` and the list comprehension a few lines below) to pass `session` as the first positional argument: `_out_bulk(session, r, soldiers, nodes, assignments, duty_types, duty_locations)`.

7. Replace the old `/swaps/{request_id}/approve` and `/swaps/{request_id}/reject` endpoints (lines 547-580) with four new endpoints:

```python
@router.post("/me/swaps/{request_id}/approve", response_model=SwapOut)
def soldier_approve(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.approve_soldier_side(session, request_id=request_id, soldier_id=user.id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


@router.post("/me/swaps/{request_id}/reject", response_model=SwapOut)
def soldier_reject(
    request_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if user.id not in (req.requesting_soldier_id, req.covering_soldier_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


class ManagerSideRequest(BaseModel):
    side: str  # "requester" | "covering"


def _side_node(session: Session, req: SwapRequest, side: str) -> HierarchyNode | None:
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        return None
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return None
    return session.get(HierarchyNode, soldier.hierarchy_node_id)


@router.post("/swaps/{request_id}/manager-approve", response_model=SwapOut)
def manager_approve(
    request_id: uuid.UUID,
    body: ManagerSideRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swap_not_found")
    if body.side not in ("requester", "covering"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_side")
    is_required_commander = svc.has_required_manager_row(
        session, request_id=request_id, side=body.side, commander_id=user.id
    )
    try:
        if is_required_commander:
            r = svc.approve_manager_row(
                session, request_id=request_id, side=body.side, commander_id=user.id, actor_id=user.id
            )
        else:
            authorize(session, user, Action.SWAP_APPROVE, target_node=_side_node(session, req, body.side))
            r = svc.approve_manager_side_override(session, request_id=request_id, side=body.side, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


@router.post("/swaps/{request_id}/manager-reject", response_model=SwapOut)
def manager_reject(
    request_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swap_not_found")
    req_node = _side_node(session, req, "requester")
    cov_node = _side_node(session, req, "covering")
    authorized = False
    for node in (req_node, cov_node):
        try:
            authorize(session, user, Action.SWAP_APPROVE, target_node=node)
            authorized = True
            break
        except HTTPException:
            continue
    if not authorized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)
```

8. In the `pending()` function's filtering logic (around line 438-457), update `_requester_node` usage so a swap shows up for a commander in *either* chain, not just the requester's. Replace:

```python
    def _requester_node(r: SwapRequest) -> HierarchyNode | None:
        s = soldiers.get(r.requesting_soldier_id)
        if s is None or s.hierarchy_node_id is None:
            return None
        return nodes.get(s.hierarchy_node_id)
```

with:

```python
    def _side_node_bulk(r: SwapRequest, soldier_id: uuid.UUID | None) -> HierarchyNode | None:
        if soldier_id is None:
            return None
        s = soldiers.get(soldier_id)
        if s is None or s.hierarchy_node_id is None:
            return None
        return nodes.get(s.hierarchy_node_id)
```

and update the two call sites that use `_requester_node(r)`:

```python
    if user.role == "admin":
        return [_out_bulk(session, r, soldiers, nodes, assignments, duty_types, duty_locations) for r in all_pending]

    roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    return [
        _out_bulk(session, r, soldiers, nodes, assignments, duty_types, duty_locations)
        for r in all_pending
        if can(
            user, Action.SWAP_APPROVE, target_node=_side_node_bulk(r, r.requesting_soldier_id), roots=roots,
            is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
        ) or can(
            user, Action.SWAP_APPROVE, target_node=_side_node_bulk(r, r.covering_soldier_id), roots=roots,
            is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
        )
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_swaps_api.py -v`
Expected: all passed

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: no failures. If any pre-existing test still posts to the now-removed `/swaps/{id}/approve` or `/swaps/{id}/reject` (search with `grep -rn "swaps/{.*}/approve\"\|swaps/{.*}/reject\"" backend/tests backend/app/routes/tests` first), update it to the new endpoint names/semantics.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/swaps.py backend/tests/integration/test_swaps_api.py
git commit -m "feat: soldier and per-commander swap approval endpoints"
```

---

### Task 4: Frontend — soldier's own Swaps page

**Files:**
- Modify: `frontend/src/api/swaps.ts`
- Modify: `frontend/src/pages/SwapsPage.tsx`

**Interfaces:**
- Consumes: `SwapManagerApprovalOut` fields from Task 3's `SwapOut` response.
- Produces: `soldierApproveSwap(id) -> Promise<SwapRequest>`, `soldierRejectSwap(id, decision_note?) -> Promise<SwapRequest>`, `managerApproveSwap(id, side) -> Promise<SwapRequest>`, `managerRejectSwap(id, decision_note?) -> Promise<SwapRequest>` in `api/swaps.ts` (Task 5 also consumes the manager ones).

- [ ] **Step 1: Update the API client**

In `frontend/src/api/swaps.ts`, add to the `SwapRequest` interface (after `requesting_soldier_node_name`):

```typescript
  requester_manager_approvals: SwapManagerApproval[];
  covering_manager_approvals: SwapManagerApproval[];
```

Add the new interface above `SwapRequest`:

```typescript
export interface SwapManagerApproval {
  commander_id: string;
  commander_name: string | null;
  approved: boolean;
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
}
```

Replace `approveSwapSide` and `rejectSwap` with:

```typescript
export async function soldierApproveSwap(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/approve`, {})).data;
}

export async function soldierRejectSwap(id: string, decision_note?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/reject`, { decision_note })).data;
}

export async function managerApproveSwap(id: string, side: "requester" | "covering"): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/manager-approve`, { side })).data;
}

export async function managerRejectSwap(id: string, decision_note?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/manager-reject`, { decision_note })).data;
}
```

- [ ] **Step 2: Extend the approval-status display to show the manager chain**

In `frontend/src/pages/SwapsPage.tsx`, replace the `ApprovalStatus` component (lines 141-150) with a version that also lists each side's manager chain:

```tsx
function ChainList({ approvals, t }: { approvals: SwapRequest["requester_manager_approvals"]; t: (k: string) => string }) {
  if (approvals.length === 0) return <span className="text-gray-400">{t("swaps.no_managers_required")}</span>;
  return (
    <span className="flex flex-wrap gap-2">
      {approvals.map((a) => (
        <span key={a.commander_id} className="inline-flex items-center gap-1">
          <SoldierLink id={a.commander_id} name={a.commander_name ?? a.commander_id.slice(0, 8)} />
          <ApprovalDot value={a.approved ? true : null} />
        </span>
      ))}
    </span>
  );
}

function ApprovalStatus({ swap, requireManagerApproval }: { swap: SwapRequest; requireManagerApproval: boolean }) {
  const { t } = useTranslation();
  if (!requireManagerApproval || swap.status !== "pending_approval") return null;
  return (
    <div className="text-xs text-gray-500 dark:text-gray-400 space-y-1 mt-1">
      <div className="flex flex-wrap gap-3">
        <span>{t("swaps.requester_approval")}: <ApprovalDot value={swap.requester_side_approved} /></span>
        <span>{t("swaps.covering_approval")}: <ApprovalDot value={swap.covering_side_approved} /></span>
      </div>
      <div className="flex flex-col gap-1">
        <span>{t("swaps.requester_managers")}: <ChainList approvals={swap.requester_manager_approvals} t={t} /></span>
        <span>{t("swaps.covering_managers")}: <ChainList approvals={swap.covering_manager_approvals} t={t} /></span>
      </div>
    </div>
  );
}
```

Add `import SoldierLink from "../components/SoldierLink";` to the top imports.

- [ ] **Step 3: Add soldier approve/decline actions**

Still in `SwapsPage.tsx`, import the new API functions (replace the `import { ... } from "../api/swaps";` block at line 9-13):

```typescript
import {
  SwapRequest, cancelSwap, createSwap, listBoard,
  listMySwaps, listIncomingSwaps, getSwapConfig, CreateSwapInput, BoardFilters,
  CoverEligibilityResult, checkCoverEligibility, soldierApproveSwap, soldierRejectSwap,
} from "../api/swaps";
```

Inside the component, add handlers near `handleCancel` (find it via `grep -n "handleCancel" frontend/src/pages/SwapsPage.tsx`):

```typescript
  const [swapRejectNote, setSwapRejectNote] = useState<Record<string, string>>({});

  async function handleSoldierApprove(id: string) {
    try { await soldierApproveSwap(id); await refresh(); }
    catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }
  async function handleSoldierReject(id: string) {
    try {
      await soldierRejectSwap(id, swapRejectNote[id]);
      setSwapRejectNote((prev) => { const next = { ...prev }; delete next[id]; return next; });
      await refresh();
    } catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }
```

In `renderMySwapCard` (requester's own side — the soldier viewing this list is always the requester), add the approve/decline controls right after the `ApprovalStatus` line, only while pending and not yet approved by this soldier:

```tsx
      {swap.status === "pending_approval" && swap.requester_side_approved !== true && (
        <div className="flex gap-2 items-center">
          <button type="button" onClick={() => handleSoldierApprove(swap.id)}
            className="bg-green-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.approve")}
          </button>
          <input
            placeholder={t("approvals.decision_note")}
            value={swapRejectNote[swap.id] ?? ""}
            onChange={(e) => setSwapRejectNote((prev) => ({ ...prev, [swap.id]: e.target.value }))}
            className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
          <button type="button" onClick={() => handleSoldierReject(swap.id)}
            className="bg-red-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.reject")}
          </button>
        </div>
      )}
```

In `renderIncomingCard` (the covering soldier's side), add the same block (with the same condition but checking `swap.covering_side_approved !== true`) right after the `ApprovalStatus` line in that function:

```tsx
      {swap.status === "pending_approval" && swap.covering_side_approved !== true && (
        <div className="flex gap-2 items-center">
          <button type="button" onClick={() => handleSoldierApprove(swap.id)}
            className="bg-green-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.approve")}
          </button>
          <input
            placeholder={t("approvals.decision_note")}
            value={swapRejectNote[swap.id] ?? ""}
            onChange={(e) => setSwapRejectNote((prev) => ({ ...prev, [swap.id]: e.target.value }))}
            className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
          <button type="button" onClick={() => handleSoldierReject(swap.id)}
            className="bg-red-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.reject")}
          </button>
        </div>
      )}
```

- [ ] **Step 4: Add missing translation keys**

Check `frontend/src/i18n/` (find the Hebrew locale file, e.g. `grep -rl "swaps.requester_approval" frontend/src/i18n/`) and add next to the existing `swaps.*` keys:

```json
"swaps.requester_managers": "מפקדי המבקש",
"swaps.covering_managers": "מפקדי המחליף",
"swaps.no_managers_required": "לא נדרש אישור מפקד"
```

- [ ] **Step 5: Manually verify in the browser**

Start the dev stack, create a swap between two soldiers under different commanders with `swaps.require_manager_approval` enabled, claim/cover it so it enters `pending_approval`, and confirm:
- both soldiers see an Approve/Decline control on their respective card until they act
- the chain list shows each required commander by name with a pending/approved dot
- after both soldiers approve, the swap stays `pending_approval` until commanders act too

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/swaps.ts frontend/src/pages/SwapsPage.tsx frontend/src/i18n/
git commit -m "feat: soldier self-approval and chain-of-command status on Swaps page"
```

---

### Task 5: Frontend — manager Approvals page

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

**Interfaces:**
- Consumes: `managerApproveSwap`, `managerRejectSwap` from Task 4's `api/swaps.ts` changes.

- [ ] **Step 1: Update imports and handlers**

In `frontend/src/pages/ApprovalsPage.tsx`, replace the swaps import block (lines 31-36):

```typescript
import {
  SwapRequest,
  managerApproveSwap,
  managerRejectSwap,
  listPendingSwaps,
} from "../api/swaps";
```

Replace `onSwapApproveSide` and `onSwapReject` (lines 209-227) with:

```typescript
  async function onSwapManagerApprove(id: string, side: "requester" | "covering") {
    try {
      await managerApproveSwap(id, side);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onSwapManagerReject(id: string) {
    try {
      await managerRejectSwap(id, swapRejectNotes[id]);
      const next = { ...swapRejectNotes };
      delete next[id];
      setSwapRejectNotes(next);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
```

- [ ] **Step 2: Update the swap tab rendering**

Replace the swap card body (lines 452-497) to show each side's soldier status plus the manager chain, with an approve button per side that's disabled once that side's manager chain is fully approved:

```tsx
            {swapItems.map(swap => {
              const requesterManagersDone = swap.requester_manager_approvals.every(a => a.approved);
              const coveringManagersDone = swap.covering_manager_approvals.every(a => a.approved);
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong>{t("swaps.requester")}:</strong>
                    <span><SoldierLink id={swap.requesting_soldier_id} name={swap.requesting_soldier_name || swap.requesting_soldier_id.slice(0, 8)} /></span>
                    {swap.requesting_soldier_node_name && <span className="text-xs text-gray-400">{swap.requesting_soldier_node_name}</span>}
                    <ApprovalDotInline value={swap.requester_side_approved} />
                  </div>
                  {swap.covering_soldier_id && (
                    <div className="flex items-center gap-2">
                      <strong>{t("swaps.covering")}:</strong>
                      <span><SoldierLink id={swap.covering_soldier_id} name={swap.covering_soldier_name || swap.covering_soldier_id.slice(0, 8)} /></span>
                      <ApprovalDotInline value={swap.covering_side_approved} />
                    </div>
                  )}
                  <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
                  <div className="text-xs text-gray-500 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{t("swaps.requester_managers")}:</span>
                      {swap.requester_manager_approvals.map(a => (
                        <span key={a.commander_id} className="inline-flex items-center gap-1">
                          <SoldierLink id={a.commander_id} name={a.commander_name ?? a.commander_id.slice(0, 8)} />
                          <ApprovalDotInline value={a.approved} />
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{t("swaps.covering_managers")}:</span>
                      {swap.covering_manager_approvals.map(a => (
                        <span key={a.commander_id} className="inline-flex items-center gap-1">
                          <SoldierLink id={a.commander_id} name={a.commander_name ?? a.commander_id.slice(0, 8)} />
                          <ApprovalDotInline value={a.approved} />
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2 items-center flex-wrap">
                    <button
                      onClick={() => onSwapManagerApprove(swap.id, "requester")}
                      disabled={requesterManagersDone}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
                    >
                      {requesterManagersDone ? "✓ " : ""}{t("approvals.approve")} ({t("swaps.requester")})
                    </button>
                    <button
                      onClick={() => onSwapManagerApprove(swap.id, "covering")}
                      disabled={coveringManagersDone}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
                    >
                      {coveringManagersDone ? "✓ " : ""}{t("approvals.approve")} ({t("swaps.covering")})
                    </button>
                    <input
                      placeholder={t("approvals.decision_note")}
                      value={swapRejectNotes[swap.id] ?? ""}
                      onChange={e => setSwapRejectNotes(prev => ({ ...prev, [swap.id]: e.target.value }))}
                      className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    />
                    <button
                      onClick={() => onSwapManagerReject(swap.id)}
                      className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                </div>
              );
            })}
```

Add a small local helper above the component (or import `ApprovalDot`-equivalent — this page doesn't currently have one, so add it near the top of the file, after the imports):

```tsx
function ApprovalDotInline({ value }: { value: boolean | null }) {
  if (value === true) return <span className="text-green-600 font-bold">✓</span>;
  if (value === false) return <span className="text-red-500 font-bold">✗</span>;
  return <span className="text-gray-400">—</span>;
}
```

- [ ] **Step 3: Manually verify in the browser**

As a commander who is the required approver for one side of a pending swap, log into `/approvals`, confirm the swap tab shows both soldiers' status and both manager chains with names, that your own side's approve button works and disables once your chain is fully approved, and that reject kills the swap.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat: chain-of-command approval UI on manager Approvals page"
```
