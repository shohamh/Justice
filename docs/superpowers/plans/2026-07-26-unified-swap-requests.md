# Unified Swap Requests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse swap-out requests to one row per `(requester, duty)`, backed by a new `swap_candidates` table so a request can attract multiple invited/marketplace candidates in parallel, each running its own commander/duty-manager approval chain — first candidate to finish approval wins, others are cancelled. Both `SwapsPage` and `ApprovalsPage` show one card per request with a per-candidate status list.

**Architecture:** `SwapRequest` loses its target/covering/approval-flag columns; a new `SwapCandidate` child table (one row per potential covering soldier, `source` = `"invited"` | `"marketplace"`) carries those per-candidate. `SwapManagerApproval` gains a nullable `swap_candidate_id` — requester-side rows stay request-scoped (shared across candidates), covering-side rows become candidate-scoped. A DB partial unique index (`requesting_soldier_id, duty_assignment_id` WHERE `status='open'`) enforces "no second open request for the same duty."

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + Vite (frontend), pytest, vitest.

## Global Constraints

- Full design spec: `docs/superpowers/specs/2026-07-26-unified-swap-requests-design.md` — read it once at the start; it has the complete rationale for every decision below.
- A candidate accepting/claiming does **not** cancel other candidates anymore — cancellation only happens when one candidate finishes full approval (`_try_finalize`'s new per-candidate race logic).
- Requester-side approval (`requester_side_approved`) is shared across all candidates on a request (one requester, one approval) — never duplicate it per candidate.
- Covering-side approval, `SwapManagerApproval` rows for `side="covering"`, and `offered_assignment_ids` are all per-candidate.
- `take_free` and its bypass-approval behavior are unaffected in spirit — only its row shape changes to fit the new schema (one parent + one immediately-`applied` candidate).
- The Telegram bot (`backend/bot/actions.py`) needs **no changes** — `swap:approve_requester` (request-scoped), `swap:approve_covering` (→ `claim_request`, still one soldier claiming), and `swap:reject` (→ `reject_request`, whole-request reject) all keep their existing signatures; confirmed during planning by reading the current bot action handlers.
- Run only targeted tests per task, not the full suite.

---

### Task 1: Data model + migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/<new>_unify_swap_requests_with_candidates.py`
- Test: Create `backend/tests/unit/test_swap_candidate_model.py`

**Interfaces:**
- Produces: `SwapCandidate` model (`swap_candidates` table) with `id`, `swap_request_id`, `soldier_id`, `source`, `status`, `offered_assignment_ids`, `soldier_side_approved`, `created_at`, `decided_at`. `SwapManagerApproval.swap_candidate_id` (nullable FK). `SwapRequest` loses `target_soldier_id`, `covering_soldier_id`, `requester_side_approved`, `covering_side_approved`, `offered_assignment_ids`; gains `open_to_marketplace`. Consumed by Task 2+ (service layer) and Task 6 (routes/schemas).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_swap_candidate_model.py`:

```python
import uuid
from datetime import date

from app.db.models import DutyAssignment, Soldier, SwapCandidate, SwapRequest
from tests.helpers import create_node, create_soldier


def test_swap_request_no_longer_has_target_or_covering_columns():
    assert not hasattr(SwapRequest, "target_soldier_id")
    assert not hasattr(SwapRequest, "covering_soldier_id")
    assert not hasattr(SwapRequest, "requester_side_approved")
    assert not hasattr(SwapRequest, "covering_side_approved")
    assert not hasattr(SwapRequest, "offered_assignment_ids")


def test_swap_request_has_open_to_marketplace_column(admin_session):
    node = create_node(admin_session, level="unit", name="swap-model-unit")
    soldier = create_soldier(admin_session, personal_number="7700001", hierarchy_node_id=node.id)
    req = SwapRequest(
        duty_assignment_id=uuid.uuid4(), duty_date=date(2026, 8, 1),
        requesting_soldier_id=soldier.id, status="open",
    )
    assert req.open_to_marketplace is False


def test_swap_candidate_defaults(admin_session):
    node = create_node(admin_session, level="unit", name="swap-model-unit-2")
    requester = create_soldier(admin_session, personal_number="7700002", hierarchy_node_id=node.id)
    candidate_soldier = create_soldier(admin_session, personal_number="7700003", hierarchy_node_id=node.id)
    req = SwapRequest(
        duty_assignment_id=uuid.uuid4(), duty_date=date(2026, 8, 1),
        requesting_soldier_id=requester.id, status="open",
    )
    admin_session.add(req)
    admin_session.flush()
    cand = SwapCandidate(
        swap_request_id=req.id, soldier_id=candidate_soldier.id, source="invited",
    )
    admin_session.add(cand)
    admin_session.flush()
    assert cand.status == "pending"
    assert cand.offered_assignment_ids == []
    assert cand.soldier_side_approved is None
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`, venv activated): `pytest tests/unit/test_swap_candidate_model.py -v`
Expected: FAIL — `SwapCandidate` does not exist / `SwapRequest` still has the old columns.

- [ ] **Step 3: Modify `SwapRequest` and add `SwapCandidate` in `backend/app/db/models.py`**

Replace the `SwapRequest` class body (currently lines 507-550) with:

```python
class SwapRequest(Base):
    __tablename__ = "swap_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    # The assignment + specific day being handed off.
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    duty_date: Mapped[date] = mapped_column(Date)
    requesting_soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    # True if any eligible soldier may claim this from the open board —
    # independent of whether specific soldiers were also invited (see
    # SwapCandidate for the actual invited/claimed parties).
    open_to_marketplace: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    # open → applied (one candidate finished approval) | rejected | cancelled
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"), default="open")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Requester's own "I still want this" confirmation — shared across every
    # candidate on this request (there's exactly one requester), auto-set
    # True the first time any candidate is accepted, same as today.
    requester_side_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    resulting_override_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_day_overrides.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    __table_args__ = (
        Index(
            "uq_swap_requests_one_open_per_requester_duty",
            "requesting_soldier_id", "duty_assignment_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )


class SwapCandidate(Base):
    __tablename__ = "swap_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    swap_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_requests.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    # "invited" (added at request-creation time) | "marketplace" (self-claimed
    # from the open board).
    source: Mapped[str] = mapped_column(Text)
    # pending (invited, awaiting response) → declined | accepted → applied | cancelled
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    offered_assignment_ids: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default_factory=list
    )
    soldier_side_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    __table_args__ = (
        sa.UniqueConstraint("swap_request_id", "soldier_id", name="uq_swap_candidate_request_soldier"),
    )
```

In `SwapManagerApproval` (currently starting at line 553, after the class edit above it will have shifted), add a new column right after `swap_request_id` and update `__table_args__`:

```python
    swap_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_requests.id", ondelete="CASCADE")
    )
    # NULL for side="requester" (shared across every candidate on the
    # request); required for side="covering" (each candidate has their own
    # commander/duty-manager chain, since they're different soldiers).
    swap_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_candidates.id", ondelete="CASCADE"), nullable=True, default=None
    )
```

and change `__table_args__` (currently lines 591-596) to:

```python
    __table_args__ = (
        sa.UniqueConstraint(
            "swap_request_id", "swap_candidate_id", "side", "commander_id", "approver_kind",
            name="uq_swap_manager_approval_request_candidate_side_person_kind",
        ),
    )
```

Check the top of `models.py` for an existing `Index` import from `sqlalchemy` — if not already imported, add it to the existing `sqlalchemy` import line (the file already imports `sa` as `import sqlalchemy as sa`, so `sa.Index(...)` also works if you prefer not to add a bare `Index` import; use whichever the file's existing style favors — check the top-of-file imports before editing).

- [ ] **Step 4: Write the Alembic migration**

Run `alembic heads` first to get the current head revision (do not hardcode a guess). Then create
`backend/alembic/versions/<generated>_unify_swap_requests_with_candidates.py`:

```python
"""unify swap requests with candidates

Revision ID: <generated>
Revises: <current head>
Create Date: 2026-07-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "<generated>"
down_revision = "<current head>"
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

    # Backfill: every existing row becomes a parent + exactly one candidate.
    # (Today's sibling-cancel-on-claim guarantees at most one non-terminal
    # row per (requester, duty) at any time, so this is a reshape, not a
    # merge — no row ever needs combining with another.)
    op.execute("""
        INSERT INTO swap_candidates (swap_request_id, soldier_id, source, status, offered_assignment_ids, soldier_side_approved, created_at, decided_at)
        SELECT
            id,
            COALESCE(covering_soldier_id, target_soldier_id),
            CASE WHEN target_soldier_id IS NULL THEN 'marketplace' ELSE 'invited' END,
            CASE status
                WHEN 'applied' THEN 'applied'
                WHEN 'open' THEN CASE WHEN covering_soldier_id IS NULL THEN 'pending' ELSE 'accepted' END
                ELSE 'cancelled'
            END,
            COALESCE(offered_assignment_ids, '[]'::jsonb),
            covering_side_approved,
            created_at,
            CASE WHEN status IN ('applied', 'rejected', 'cancelled') THEN updated_at ELSE NULL END
        FROM swap_requests
        WHERE COALESCE(covering_soldier_id, target_soldier_id) IS NOT NULL;
    """)

    op.execute("""
        UPDATE swap_requests SET open_to_marketplace = true WHERE target_soldier_id IS NULL;
    """)

    # Re-point covering-side SwapManagerApproval rows at the new candidate.
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
```

- [ ] **Step 5: Apply the migration and run the test**

Run: `alembic upgrade head`
Then: `pytest tests/unit/test_swap_candidate_model.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_unify_swap_requests_with_candidates.py backend/tests/unit/test_swap_candidate_model.py
git commit -m "feat: add swap_candidates table, collapse swap_requests to one row per duty"
```

---

### Task 2: Service — create + claim rewrite

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/tests/unit/test_swaps_service.py` (create if it doesn't already exist — check first)

**Interfaces:**
- Consumes: `SwapCandidate`, `SwapRequest.open_to_marketplace` (Task 1).
- Produces: `create_request(...)` now takes `open_to_marketplace: bool = False` and always returns a single `SwapRequest` (never a list); `claim_request(...)` creates/reuses a `SwapCandidate` instead of mutating parent scalar columns. Consumed by Task 6 (routes).

- [ ] **Step 1: Check for an existing test file**

Run: `ls backend/tests/unit/ | grep -i swap` and `ls backend/tests/integration/ | grep -i swap`
If a service-level unit test file for swaps already exists, add to it; otherwise create `backend/tests/unit/test_swaps_service.py`. If existing integration tests reference `create_request`/`claim_request` directly (not just through the route), read them first so this task's changes don't silently break their assumptions — note any such files in your report.

- [ ] **Step 2: Write the failing tests**

Add (or create the file with):

```python
import uuid
from datetime import date, timedelta

import pytest

from app.db.models import DutyAssignment, SwapCandidate, SwapRequest
from app.services import swaps as svc
from app.services.swaps import SwapError
from tests.helpers import create_node, create_soldier


def _published_assignment(session, *, soldier_id, node_id):
    from app.db.models import DutyType, DutyLocation
    dt = session.query(DutyType).first() or DutyType(name="Guard", node_id=node_id, min_rank=None)
    if dt.id is None:
        session.add(dt)
        session.flush()
    loc = session.query(DutyLocation).first() or DutyLocation(name="Base", node_id=node_id)
    if loc.id is None:
        session.add(loc)
        session.flush()
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=11),
        status="published",
    )
    session.add(a)
    session.flush()
    return a


def test_create_request_combining_targets_and_marketplace(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-1")
    requester = create_soldier(admin_session, personal_number="7710001", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7710002", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
        open_to_marketplace=True,
    )
    admin_session.flush()

    assert isinstance(req, SwapRequest)
    assert req.open_to_marketplace is True
    candidates = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()
    assert len(candidates) == 1
    assert candidates[0].soldier_id == target.id
    assert candidates[0].source == "invited"
    assert candidates[0].status == "pending"


def test_create_request_rejects_second_open_request_for_same_duty(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-2")
    requester = create_soldier(admin_session, personal_number="7710003", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="already_pending"):
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )


def test_claim_request_creates_marketplace_candidate_without_cancelling_invited(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-3")
    requester = create_soldier(admin_session, personal_number="7710004", hierarchy_node_id=node.id)
    invited = create_soldier(admin_session, personal_number="7710005", hierarchy_node_id=node.id)
    claimant = create_soldier(admin_session, personal_number="7710006", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[invited.id], reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=claimant.id, actor_id=claimant.id)
    admin_session.flush()

    candidates = {c.soldier_id: c for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()}
    assert len(candidates) == 2
    assert candidates[invited.id].status == "pending"  # untouched — no more cancel-on-claim
    assert candidates[claimant.id].source == "marketplace"
    assert candidates[claimant.id].soldier_side_approved is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_swaps_service.py -v`
Expected: FAIL — `create_request` doesn't accept `open_to_marketplace`, no `SwapCandidate` rows get created, claim still mutates the parent.

- [ ] **Step 4: Rewrite `create_request` / `_create_single_request` / `claim_request` in `backend/app/services/swaps.py`**

First, add `SwapCandidate` to the `from app.db.models import (...)` block at the top of the file (it currently imports `SwapRequest`, `SwapManagerApproval`, and others — add `SwapCandidate` alongside them; this single import addition covers every use of `SwapCandidate` introduced across this task and Tasks 3-5, so it only needs doing once, here).

Replace `create_request` (lines 60-97) and `_create_single_request` (lines 100-170) with:

```python
def create_request(
    session: Session,
    *,
    requesting_soldier_id: uuid.UUID,
    duty_assignment_id: uuid.UUID,
    target_soldier_id: uuid.UUID | None,
    reason: str | None,
    target_soldier_ids: list[uuid.UUID] | None = None,
    open_to_marketplace: bool = False,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Create (or extend) the one open SwapRequest for this (requester, duty),
    with a SwapCandidate row per invited target plus optional marketplace
    visibility. Always returns a single SwapRequest — no more fan-out into
    multiple parent rows."""
    targets = target_soldier_ids if target_soldier_ids is not None else (
        [target_soldier_id] if target_soldier_id is not None else []
    )
    if len(targets) > _max_specific_targets(session):
        raise SwapError("too_many_targets")
    if not targets and not open_to_marketplace:
        raise SwapError("no_targets_specified")

    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if assignment.soldier_id != requesting_soldier_id:
        raise SwapError("not_your_duty")
    if assignment.status != "published":
        raise SwapError("not_published")

    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == duty_assignment_id,
            SwapRequest.requesting_soldier_id == requesting_soldier_id,
            SwapRequest.status == "open",
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SwapError("already_pending")

    req = SwapRequest(
        duty_assignment_id=duty_assignment_id,
        duty_date=assignment.start_date,
        requesting_soldier_id=requesting_soldier_id,
        reason=reason,
        status="open",
        open_to_marketplace=open_to_marketplace,
    )
    session.add(req)
    session.flush()

    for target_id in targets:
        _add_invited_candidate(
            session, req=req, requesting_soldier_id=requesting_soldier_id,
            target_soldier_id=target_id, actor_id=actor_id,
        )

    write_audit(
        session, actor_id=actor_id, action="swap.create", entity_type="swap_request",
        entity_id=req.id,
        after={
            "duty_assignment_id": str(duty_assignment_id),
            "duty_date": req.duty_date.isoformat(),
            "target_soldier_ids": [str(t) for t in targets],
            "open_to_marketplace": open_to_marketplace,
            "status": "open",
        },
    )
    session.flush()
    return req


def _add_invited_candidate(
    session: Session, *, req: SwapRequest, requesting_soldier_id: uuid.UUID,
    target_soldier_id: uuid.UUID, actor_id: uuid.UUID | None,
) -> SwapCandidate:
    if target_soldier_id == requesting_soldier_id:
        raise SwapError("cannot_target_self")
    eligible, reason = check_soldier_for_assignment(session, target_soldier_id, req.duty_assignment_id)
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
    _enforce_hierarchy_level_restriction(
        session, requesting_soldier_id=requesting_soldier_id, other_soldier_id=target_soldier_id
    )
    candidate = SwapCandidate(swap_request_id=req.id, soldier_id=target_soldier_id, source="invited")
    session.add(candidate)
    session.flush()
    create_notification(
        session, soldier_id=target_soldier_id, type=NotificationType.swap_offer_incoming,
        title="הגיעה בקשת החלפה עבורך", reference_type="swap_request", reference_id=req.id,
        actor_id=actor_id,
    )
    return candidate
```

Replace the body of `claim_request` (lines 542-633) with:

```python
def claim_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")
    if covering_soldier_id == req.requesting_soldier_id:
        raise SwapError("cannot_cover_own")
    if session.get(Soldier, covering_soldier_id) is None:
        raise SwapError("soldier_not_found")

    existing_candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == covering_soldier_id,
        )
    ).scalar_one_or_none()

    if existing_candidate is None:
        if not req.open_to_marketplace:
            raise SwapError("not_targeted_at_you")
        eligible, reason = check_soldier_for_assignment(session, covering_soldier_id, req.duty_assignment_id)
        if not eligible:
            raise SwapError(f"cover_not_eligible:{reason}")
        _enforce_hierarchy_level_restriction(
            session, requesting_soldier_id=req.requesting_soldier_id, other_soldier_id=covering_soldier_id,
        )
        candidate = SwapCandidate(swap_request_id=request_id, soldier_id=covering_soldier_id, source="marketplace")
        session.add(candidate)
    else:
        if existing_candidate.status not in ("pending",):
            raise SwapError("already_pending")
        candidate = existing_candidate

    before_status = candidate.status
    candidate.status = "accepted"
    candidate.soldier_side_approved = True
    req.requester_side_approved = True  # asking already implied consent
    write_audit(
        session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
        entity_id=req.id, before={"candidate_status": before_status},
        after={"candidate_status": "accepted", "soldier_id": str(covering_soldier_id)},
    )
    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_offer,
        title="הייתה הצעת החלפה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req
```

Note: `_try_finalize` is rewritten in Task 4 — for this task, a temporary pass-through is fine (`_try_finalize` still exists from before Task 4 lands; if it references removed columns and breaks, stub it to a no-op with a `# TODO(Task 4)` comment for this task only, since Task 4 replaces it completely — check whether Task 4 is being executed as a separate subagent dispatch; if so leave a minimal working stub here so this task's own tests pass in isolation).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_swaps_service.py -v`
Expected: PASS (all 3 new tests). If `_try_finalize` isn't yet updated (Task 4 not done), the claim test should still pass since it only asserts candidate/status shape, not finalization.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "feat: rewrite swap create/claim to use SwapCandidate instead of parent fan-out"
```

---

### Task 3: Service — soldier-side approve/reject rewrite

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/tests/unit/test_swaps_service.py`

**Interfaces:**
- Consumes: `SwapCandidate` (Task 1), `claim_request` (Task 2).
- Produces: `approve_soldier_side(session, *, request_id, soldier_id, actor_id)` now resolves the caller's own candidate row and approves/declines it, never the whole request. Consumed by Task 6 (routes).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_swaps_service.py`:

```python
def test_approve_soldier_side_approves_only_the_callers_candidate(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-4")
    requester = create_soldier(admin_session, personal_number="7710007", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710008", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710009", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.flush()

    cands = {c.soldier_id: c for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()}
    assert cands[a.id].soldier_side_approved is True
    assert cands[a.id].status == "accepted"
    assert cands[b.id].soldier_side_approved is None
    assert cands[b.id].status == "pending"


def test_approve_soldier_side_requester_shared_across_candidates(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-5")
    requester = create_soldier(admin_session, personal_number="7710010", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710011", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)
    admin_session.flush()
    admin_session.refresh(req)
    assert req.requester_side_approved is True


def test_approve_soldier_side_rejects_for_a_non_party(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-6")
    requester = create_soldier(admin_session, personal_number="7710012", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number="7710013", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="not_a_party"):
        svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=stranger.id, actor_id=stranger.id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_swaps_service.py -k "approve_soldier_side" -v`
Expected: FAIL — `approve_soldier_side` still assumes single `covering_soldier_id` on the parent.

- [ ] **Step 3: Rewrite `approve_soldier_side` in `backend/app/services/swaps.py`**

Replace lines 274-295 with:

```python
def approve_soldier_side(
    session: Session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    if soldier_id == req.requesting_soldier_id:
        req.requester_side_approved = True
        write_audit(
            session, actor_id=actor_id or soldier_id, action="swap.soldier_approve",
            entity_type="swap_request", entity_id=req.id, after={"soldier_id": str(soldier_id), "side": "requester"},
        )
        session.flush()
        return req
    candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == soldier_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise SwapError("not_a_party")
    candidate.soldier_side_approved = True
    if candidate.status == "pending":
        candidate.status = "accepted"
    write_audit(
        session, actor_id=actor_id or soldier_id, action="swap.soldier_approve",
        entity_type="swap_request", entity_id=req.id,
        after={"soldier_id": str(soldier_id), "side": "covering", "candidate_id": str(candidate.id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id or soldier_id)
    session.flush()
    return req
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_swaps_service.py -k "approve_soldier_side" -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "feat: rewrite soldier-side swap approval to act on a single candidate"
```

---

### Task 4: Service — manager approve/reject/override + finalize race + candidate decline

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/tests/unit/test_swaps_service.py`

**Interfaces:**
- Consumes: `SwapCandidate` (Task 1), rewritten create/claim/soldier-approve (Tasks 2-3).
- Produces: `is_chain_commander_for_side`, `_qualifying_rows_for_actor`, `_get_or_create_row`, `approve_manager_row`, `reject_manager_row`, `approve_manager_side`, `approve_manager_side_override`, `_all_approved`, `_try_finalize` all take an explicit `candidate_id: uuid.UUID | None` (None only valid for `side="requester"`). `_try_finalize` now races candidates and cancels losers on the first full approval. Consumed by Task 5 (reject/cancel) and Task 6 (routes).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_swaps_service.py`:

```python
def test_finalize_first_fully_approved_candidate_wins_and_cancels_others(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-7")
    requester = create_soldier(admin_session, personal_number="7710014", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710015", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710016", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=b.id, actor_id=b.id)
    admin_session.flush()

    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    # No commander/duty-manager chain in this test setup (soldiers have no
    # assigned commander), so _all_approved should already be true for both —
    # finalize picks whichever _try_finalize call reaches it first (a's,
    # since it ran first above).
    admin_session.refresh(req)
    assert req.status == "applied"
    cand_a2 = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    cand_b2 = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=b.id).one()
    assert cand_a2.status == "applied"
    assert cand_b2.status == "cancelled"


def test_declined_candidate_does_not_affect_other_candidates(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-8")
    requester = create_soldier(admin_session, personal_number="7710017", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710018", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710019", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.decline_candidate(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.flush()

    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    cand_b = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=b.id).one()
    admin_session.refresh(req)
    assert cand_a.status == "declined"
    assert cand_b.status == "pending"
    assert req.status == "open"


def test_finalize_immediate_when_manager_approval_not_required(admin_session):
    """When swaps.require_manager_approval is off, both soldier-side
    confirmations alone finalize the request — no commander/duty-manager
    chain check should block it (regression check for the
    _candidate_fully_approved short-circuit)."""
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)

    node = create_node(admin_session, level="unit", name="swap-svc-unit-11")
    requester = create_soldier(admin_session, personal_number="7710025", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710026", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=a.id, actor_id=a.id)
    admin_session.flush()

    admin_session.refresh(req)
    assert req.status == "applied"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_swaps_service.py -k "finalize or declined" -v`
Expected: FAIL — `_try_finalize` doesn't race candidates yet; `decline_candidate` doesn't exist.

- [ ] **Step 3: Rewrite the manager-approval + finalize functions in `backend/app/services/swaps.py`**

Replace `is_chain_commander_for_side` through `_try_finalize` (originally lines 220-274 covering `_has_decision`, `_all_approved`, `_try_finalize`, plus lines 298-511 covering `is_chain_commander_for_side` through `approve_manager_side_override`) with:

```python
def _has_decision(session: Session, request_id: uuid.UUID, candidate_id: uuid.UUID | None, side: str, kind: str, *, approved: bool) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.swap_candidate_id == candidate_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approver_kind == kind,
            SwapManagerApproval.approved == approved,  # noqa: E712
        ).limit(1)
    ).first() is not None


def _candidate_fully_approved(session: Session, req: SwapRequest, candidate: SwapCandidate) -> bool:
    """A candidate is ready to finalize once: the requester has approved
    (shared across all candidates), this candidate has approved, and — only
    when manager approval is configured as required at all
    (`swaps.require_manager_approval`) — both sides' live commander/duty-
    manager chains (if any) have an approved decision row. When manager
    approval isn't required, the two soldier-side confirmations alone are
    sufficient (matches today's `not _require_approval` bypass in the old
    claim_request)."""
    if not (req.requester_side_approved and candidate.soldier_side_approved):
        return False
    if not _require_approval(session):
        return True
    require_dm = _require_duty_manager_approval(session)
    if commander_chain_for_soldier(session, req.requesting_soldier_id) and not _has_decision(session, req.id, None, "requester", "commander", approved=True):
        return False
    if require_dm and duty_manager_chain_for_soldier(session, req.requesting_soldier_id) and not _has_decision(session, req.id, None, "requester", "duty_manager", approved=True):
        return False
    if commander_chain_for_soldier(session, candidate.soldier_id) and not _has_decision(session, req.id, candidate.id, "covering", "commander", approved=True):
        return False
    if require_dm and duty_manager_chain_for_soldier(session, candidate.soldier_id) and not _has_decision(session, req.id, candidate.id, "covering", "duty_manager", approved=True):
        return False
    return True


def _try_finalize(session: Session, req: SwapRequest, actor_id: uuid.UUID | None) -> None:
    """Race: check every live (pending/accepted) candidate; the first one
    found fully approved wins — applies the cover, marks the request
    applied, and cancels every other still-live candidate. Candidates are
    checked in creation order so ties resolve deterministically (earliest
    invited/claimed wins). Runs the same regardless of the
    require-manager-approval setting — `_candidate_fully_approved` is what
    varies its bar based on that setting, not this function."""
    if req.status != "open":
        return
    candidates = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == req.id,
            SwapCandidate.status.in_(["pending", "accepted"]),
        ).order_by(SwapCandidate.created_at.asc())
    ).scalars().all()
    winner = next((c for c in candidates if _candidate_fully_approved(session, req, c)), None)
    if winner is None:
        return
    _apply_cover(session, req=req, candidate=winner, actor_id=actor_id)
    winner.status = "applied"
    winner.decided_at = datetime.utcnow()
    req.status = "applied"
    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_accepted,
        title="בקשת ההחלפה בוצעה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    create_notification(
        session, soldier_id=winner.soldier_id, type=NotificationType.swap_accepted,
        title="בקשת ההחלפה בוצעה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    for other in candidates:
        if other.id == winner.id:
            continue
        other.status = "cancelled"
        other.decided_at = datetime.utcnow()
        create_notification(
            session, soldier_id=other.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה בוטלה — כבר נמצא מחליף אחר", reference_type="swap_request",
            reference_id=req.id, actor_id=actor_id,
        )
    write_audit(
        session, actor_id=actor_id, action="swap.finalize", entity_type="swap_request",
        entity_id=req.id, after={"winning_candidate_id": str(winner.id), "soldier_id": str(winner.soldier_id)},
    )


def decline_candidate(
    session: Session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None,
) -> SwapCandidate:
    """A candidate soldier declines their own invite/claim — only removes
    them from contention, never touches the parent request or other
    candidates."""
    candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == soldier_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise SwapError("not_a_party")
    if candidate.status not in ("pending", "accepted"):
        raise SwapError("not_pending")
    candidate.status = "declined"
    candidate.decided_at = datetime.utcnow()
    write_audit(
        session, actor_id=actor_id or soldier_id, action="swap.candidate_decline",
        entity_type="swap_request", entity_id=request_id, after={"soldier_id": str(soldier_id)},
    )
    session.flush()
    return candidate


def is_chain_commander_for_side(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
) -> bool:
    req = session.get(SwapRequest, request_id)
    if req is None:
        return False
    if side == "requester":
        soldier_id = req.requesting_soldier_id
    else:
        if candidate_id is None:
            return False
        candidate = session.get(SwapCandidate, candidate_id)
        soldier_id = candidate.soldier_id if candidate else None
    if soldier_id is None:
        return False
    if commander_id in commander_chain_for_soldier(session, soldier_id):
        return True
    if _require_duty_manager_approval(session) and commander_id in duty_manager_chain_for_soldier(session, soldier_id):
        return True
    return False


def _qualifying_rows_for_actor(
    session: Session, req: SwapRequest, actor_id: uuid.UUID, candidate_id: uuid.UUID | None,
) -> list[tuple[str, str]]:
    """Every (side, kind) `actor_id` is CURRENTLY a required approver for on
    this request — requester side always checked; covering side only if
    `candidate_id` is given (a manager acts on one candidate at a time)."""
    require_dm = _require_duty_manager_approval(session)
    out: list[tuple[str, str]] = []
    if actor_id in commander_chain_for_soldier(session, req.requesting_soldier_id):
        out.append(("requester", "commander"))
    if require_dm and actor_id in duty_manager_chain_for_soldier(session, req.requesting_soldier_id):
        out.append(("requester", "duty_manager"))
    if candidate_id is not None:
        candidate = session.get(SwapCandidate, candidate_id)
        if candidate is not None:
            if actor_id in commander_chain_for_soldier(session, candidate.soldier_id):
                out.append(("covering", "commander"))
            if require_dm and actor_id in duty_manager_chain_for_soldier(session, candidate.soldier_id):
                out.append(("covering", "duty_manager"))
    return out


def _get_or_create_row(
    session: Session, *, request_id: uuid.UUID, candidate_id: uuid.UUID | None, side: str, actor_id: uuid.UUID, kind: str,
) -> SwapManagerApproval:
    row = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.swap_candidate_id == candidate_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == actor_id,
            SwapManagerApproval.approver_kind == kind,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SwapManagerApproval(
            swap_request_id=request_id, swap_candidate_id=candidate_id, side=side, commander_id=actor_id, approver_kind=kind,
        )
        session.add(row)
    return row


def approve_manager_row(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id, candidate_id)
    if not qualifying:
        raise SwapError("not_required_approver")
    now = datetime.utcnow()
    for side, kind in qualifying:
        row_candidate_id = candidate_id if side == "covering" else None
        row = _get_or_create_row(session, request_id=request_id, candidate_id=row_candidate_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            write_audit(
                session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
                entity_id=req.id, after={"side": side, "kind": kind, "candidate_id": str(candidate_id) if candidate_id else None},
            )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def reject_manager_row(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
    decision_note: str | None = None,
) -> SwapRequest:
    """Stamps rejected on every (side, kind) row the actor qualifies for,
    then declines just that candidate (or, if side="requester" was the
    only qualifying side, rejects the whole request — a requester-side
    manager rejection means the requester's own chain says no, which kills
    the ask entirely regardless of which candidates exist)."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id, candidate_id)
    now = datetime.utcnow()
    sides_rejected: set[str] = set()
    for side, kind in qualifying:
        row_candidate_id = candidate_id if side == "covering" else None
        row = _get_or_create_row(session, request_id=request_id, candidate_id=row_candidate_id, side=side, actor_id=actor_id, kind=kind)
        if not row.rejected:
            row.rejected = True
            row.rejected_by = actor_id
            row.rejected_at = now
        sides_rejected.add(side)
    session.flush()
    if "requester" in sides_rejected:
        return reject_request(session, request_id=request_id, decision_note=decision_note, actor_id=actor_id)
    if candidate_id is not None:
        candidate = session.get(SwapCandidate, candidate_id)
        if candidate is not None and candidate.status in ("pending", "accepted"):
            candidate.status = "cancelled"
            candidate.decided_at = now
            create_notification(
                session, soldier_id=candidate.soldier_id, type=NotificationType.swap_rejected,
                title="בקשת ההחלפה נדחתה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
            )
    session.flush()
    return req


def approve_manager_side(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID,
    is_authorized_override: "Callable[[], bool] | bool",
    candidate_id: uuid.UUID | None = None,
) -> SwapRequest:
    if is_chain_commander_for_side(session, request_id=request_id, side=side, commander_id=actor_id, candidate_id=candidate_id):
        return approve_manager_row(session, request_id=request_id, actor_id=actor_id, candidate_id=candidate_id)
    authorized = is_authorized_override() if callable(is_authorized_override) else is_authorized_override
    if not authorized:
        raise SwapError("forbidden")
    return approve_manager_side_override(session, request_id=request_id, side=side, actor_id=actor_id, candidate_id=candidate_id)


def _override_authorized_kinds(
    session: Session, *, actor_id: uuid.UUID, side_node: HierarchyNode | None
) -> set[str]:
    from app.auth.authz import _node_in_scope, is_commander, is_duty_manager, scope_root_ids

    actor = session.get(Soldier, actor_id)
    if actor is not None and actor.role == "admin":
        return {"commander", "duty_manager"}
    kinds: set[str] = set()
    if is_duty_manager(session, actor_id):
        kinds.add("duty_manager")
    if actor is not None and is_commander(session, actor_id):
        if _node_in_scope(side_node, scope_root_ids(session, actor)):
            kinds.add("commander")
    return kinds


def approve_manager_side_override(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    if side == "requester":
        soldier_id = req.requesting_soldier_id
    else:
        if candidate_id is None:
            raise SwapError("no_soldier_for_side")
        candidate = session.get(SwapCandidate, candidate_id)
        soldier_id = candidate.soldier_id if candidate else None
    if soldier_id is None:
        raise SwapError("no_soldier_for_side")
    side_node = None
    soldier = session.get(Soldier, soldier_id)
    if soldier is not None and soldier.hierarchy_node_id is not None:
        side_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    allowed_kinds = _override_authorized_kinds(session, actor_id=actor_id, side_node=side_node)
    if not allowed_kinds:
        raise SwapError("forbidden")
    kinds_needed = []
    if commander_chain_for_soldier(session, soldier_id):
        kinds_needed.append("commander")
    if _require_duty_manager_approval(session) and duty_manager_chain_for_soldier(session, soldier_id):
        kinds_needed.append("duty_manager")
    kinds_to_clear = [k for k in kinds_needed if k in allowed_kinds]
    now = datetime.utcnow()
    cleared = 0
    row_candidate_id = candidate_id if side == "covering" else None
    for kind in kinds_to_clear:
        row = _get_or_create_row(session, request_id=request_id, candidate_id=row_candidate_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            cleared += 1
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve_override", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "rows_cleared": cleared, "candidate_id": str(candidate_id) if candidate_id else None},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req
```

`_apply_cover` (unchanged in position, but its signature changes — see Task 5) must be updated in this same task since `_try_finalize` above now calls it with a `candidate=` kwarg: rename its `req.covering_soldier_id` reference to `candidate.soldier_id` and have it set `req.resulting_override_id`. Full replacement is in Task 5's step — apply that change now as part of this task if Task 5 hasn't landed yet (they're tightly coupled; if executing sequentially, do `_apply_cover` here too):

```python
def _apply_cover(
    session: Session, *, req: SwapRequest, candidate: SwapCandidate, actor_id: uuid.UUID | None
) -> None:
    """Translate an agreed swap into duty_day_overrides for every day of the assignment."""
    assignment = session.get(DutyAssignment, req.duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    first_ov = None
    current = assignment.start_date
    while current < assignment.end_date:  # end_date is exclusive
        try:
            ov = assignments_svc.set_day_override(
                session, assignment=assignment, date=current,
                effective_soldier_id=candidate.soldier_id, reason="replacement", actor_id=actor_id,
            )
        except assignments_svc.AssignmentError as exc:
            raise SwapError(f"cover_blocked:{exc}") from exc
        if first_ov is None:
            first_ov = ov
        current += timedelta(days=1)
    req.resulting_override_id = first_ov.id if first_ov else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_swaps_service.py -v`
Expected: PASS (all tests so far, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "feat: race parallel swap candidates through approval, first fully-approved wins"
```

---

### Task 5: Service — reject/cancel/take_free/cover_offer adaptation

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/tests/unit/test_swaps_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: `reject_request`, `cancel_request` cascade-cancel every live candidate. `take_free` creates parent+one-applied-candidate. `cover_offer` operates on a `candidate_id`. Consumed by Task 6 (routes).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_swaps_service.py`:

```python
def test_cancel_request_cascades_to_all_live_candidates(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-9")
    requester = create_soldier(admin_session, personal_number="7710020", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710021", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710022", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.cancel_request(admin_session, request_id=req.id, actor_id=requester.id)
    admin_session.flush()

    admin_session.refresh(req)
    assert req.status == "cancelled"
    for sid in (a.id, b.id):
        cand = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=sid).one()
        assert cand.status == "cancelled"


def test_take_free_creates_one_applied_candidate(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-10")
    owner = create_soldier(admin_session, personal_number="7710023", hierarchy_node_id=node.id)
    taker = create_soldier(admin_session, personal_number="7710024", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=owner.id, node_id=node.id)

    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=taker.id, actor_id=taker.id)
    admin_session.flush()

    assert req.status == "applied"
    cand = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).one()
    assert cand.soldier_id == taker.id
    assert cand.source == "marketplace"
    assert cand.status == "applied"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_swaps_service.py -k "cancel_request_cascades or take_free" -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `reject_request`, `cancel_request`, `take_free`, `cover_offer`**

Replace `reject_request` (lines 636-669) with:

```python
def reject_request(
    session: Session, *, request_id: uuid.UUID, decision_note: str | None = None, actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_rejectable")
    before = {"status": req.status}
    req.status = "rejected"
    req.decision_note = decision_note
    req.rejected_by = actor_id
    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_rejected,
        title="בקשת ההחלפה נדחתה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    live_candidates = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.status.in_(["pending", "accepted"]),
        )
    ).scalars().all()
    now = datetime.utcnow()
    for candidate in live_candidates:
        candidate.status = "cancelled"
        candidate.decided_at = now
        create_notification(
            session, soldier_id=candidate.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה נדחתה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
        )
    write_audit(
        session, actor_id=actor_id, action="swap.reject", entity_type="swap_request",
        entity_id=req.id, before=before,
        after={"status": "rejected", "decision_note": decision_note, "rejected_by": str(actor_id) if actor_id else None},
    )
    session.flush()
    return req
```

Replace `cancel_request` (lines 672-696) with:

```python
def cancel_request(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_cancellable")
    before = {"status": req.status}
    req.status = "cancelled"
    live_candidates = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.status.in_(["pending", "accepted"]),
        )
    ).scalars().all()
    now = datetime.utcnow()
    for candidate in live_candidates:
        candidate.status = "cancelled"
        candidate.decided_at = now
        create_notification(
            session, soldier_id=candidate.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה בוטלה ע\"י המבקש", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
        )
    write_audit(
        session, actor_id=actor_id, action="swap.cancel", entity_type="swap_request",
        entity_id=req.id, before=before, after={"status": "cancelled"},
    )
    session.flush()
    return req
```

Replace the `SwapRequest(...)` construction + `_apply_cover(...)` call inside `take_free` (lines 760-781) with:

```python
    req = SwapRequest(
        duty_assignment_id=assignment_id,
        duty_date=assignment.start_date,
        requesting_soldier_id=assignment.soldier_id,
        status="open",
        requester_side_approved=True,
    )
    session.add(req)
    session.flush()
    candidate = SwapCandidate(
        swap_request_id=req.id, soldier_id=covering_soldier_id, source="marketplace",
        status="accepted", soldier_side_approved=True,
    )
    session.add(candidate)
    session.flush()

    create_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.swap_offer,
        title="חייל אחר לקח את התורנות שלך", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )

    _apply_cover(session, req=req, candidate=candidate, actor_id=actor_id)
    candidate.status = "applied"
    candidate.decided_at = datetime.utcnow()
    req.status = "applied"
```

(Keep the surrounding `write_audit(...)` call at the end of `take_free` as-is — it already references `req`/`covering_soldier_id` generically and doesn't need column-shape changes.)

Replace `cover_offer` (currently lines 796-867) with:

```python
def cover_offer(
    session: Session,
    *,
    swap_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    offered_assignment_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Covering soldier responds to an open swap request (from board or
    incoming), optionally attaching a counter-offer of their own assignments."""
    req = session.get(SwapRequest, swap_id)
    if req is None:
        raise SwapError("swap_not_found")
    if req.status != "open":
        raise SwapError("swap_not_open")
    if req.requesting_soldier_id == covering_soldier_id:
        raise SwapError("cannot_cover_own_swap")
    eligible, reason = check_soldier_for_assignment(session, covering_soldier_id, req.duty_assignment_id)
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
    _enforce_hierarchy_level_restriction(
        session, requesting_soldier_id=req.requesting_soldier_id, other_soldier_id=covering_soldier_id,
    )

    candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == swap_id,
            SwapCandidate.soldier_id == covering_soldier_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        if not req.open_to_marketplace:
            raise SwapError("not_targeted_at_you")
        candidate = SwapCandidate(swap_request_id=swap_id, soldier_id=covering_soldier_id, source="marketplace")
        session.add(candidate)
    elif candidate.status != "pending":
        raise SwapError("already_pending")

    candidate.offered_assignment_ids = [str(aid) for aid in offered_assignment_ids]
    candidate.status = "accepted"
    candidate.soldier_side_approved = True
    req.requester_side_approved = True

    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_offer,
        title="הגיעה הצעה לכיסוי הבקשה שלך", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    write_audit(
        session, actor_id=actor_id, action="swap.cover_offer", entity_type="swap_request",
        entity_id=req.id, after={"soldier_id": str(covering_soldier_id), "candidate_id": str(candidate.id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req
```

Note this drops the old `if not _require_approval(session): _apply_cover(...) immediately` branch in favor of always calling `_try_finalize` — Task 4's `_candidate_fully_approved` already handles the no-manager-approval-required config by short-circuiting to `True` once both soldier-side confirmations are set, so finalize still fires immediately in that config via the same code path as the normal case.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_swaps_service.py -v`
Expected: PASS (full file, all tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "feat: cascade reject/cancel to all live swap candidates, adapt take_free and cover_offer"
```

---

### Task 6: Routes + schemas

**Files:**
- Modify: `backend/app/routes/swaps.py`
- Test: `backend/tests/integration/test_swaps_api.py` (create if it doesn't already exist — check first with `ls backend/tests/integration/ | grep -i swap`)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: `SwapOut.candidates: list[SwapCandidateOut]` replacing the flat `target_soldier_id`/`covering_soldier_id`/`*_manager_approvals` fields. `POST /me/swaps` body gains `open_to_marketplace: bool`. `/me/swaps/{id}/approve`, `/reject` resolve the caller's own candidate server-side (no new body field). `/swaps/{id}/manager-approve`, `/manager-reject` gain `candidate_id: uuid.UUID | None` in the body. Consumed by Task 7 (frontend types).

- [ ] **Step 1: Write the failing tests**

Create (or extend) `backend/tests/integration/test_swaps_api.py` — read any existing swap integration tests first (`grep -rl "swaps" backend/tests/integration/*.py`) to match existing fixture patterns (assignment creation helpers, auth headers), then add:

```python
def test_create_swap_with_both_targets_and_marketplace(client, admin_session):
    # ... use the same assignment/soldier creation helpers as existing swap
    # integration tests in this file; POST to /api/me/swaps with both
    # target_soldier_ids and open_to_marketplace=True, assert response has
    # a single id (not a list) and body["candidates"] has one "invited" entry.
    pass


def test_swap_out_shape_has_candidates_list_not_flat_covering_fields(client, admin_session):
    # Assert response body has "candidates" key (list) and does NOT have
    # top-level "covering_soldier_id" / "target_soldier_id" keys anymore.
    pass


def test_manager_approve_requires_candidate_id_for_covering_side(client, admin_session):
    # POST /api/swaps/{id}/manager-approve with side="covering" and no
    # candidate_id -> 400; with a valid candidate_id -> 200.
    pass
```

Write these fully once you've read the existing test file's exact fixture helpers — this brief intentionally leaves the fixture setup for you to match the file's established conventions rather than guessing them; do not skip writing real assertions in place of the `pass` placeholders above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_swaps_api.py -v`
Expected: FAIL — old schema/routes still in place.

- [ ] **Step 3: Rewrite `backend/app/routes/swaps.py`**

Add a new schema after `SwapManagerApprovalOut` (currently ending line 44):

```python
class SwapCandidateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str | None = None
    source: str
    status: str
    soldier_side_approved: bool | None = None
    offered_assignment_ids: list[str] = []
    manager_approvals: list[SwapManagerApprovalOut] = []
```

Replace `SwapOut` (lines 47-76) with:

```python
class SwapOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    duty_date: date
    requesting_soldier_id: uuid.UUID
    open_to_marketplace: bool
    status: str
    reason: str | None
    requester_side_approved: bool | None
    decision_note: str | None
    rejected_by_name: str | None = None
    created_at: datetime
    duty_type_name: str | None = None
    duty_location_name: str | None = None
    duty_type_id: uuid.UUID | None = None
    duty_location_id: uuid.UUID | None = None
    duty_start_date: date | None = None
    duty_end_date: date | None = None
    duty_shift_id: uuid.UUID | None = None
    warnings: list[str] = []
    requesting_soldier_name: str | None = None
    requesting_commander_name: str | None = None
    requesting_soldier_node_name: str | None = None
    requester_manager_approvals: list[SwapManagerApprovalOut] = []
    candidates: list[SwapCandidateOut] = []
```

Replace `CreateSwapRequest` (lines 79-83):

```python
class CreateSwapRequest(BaseModel):
    duty_assignment_id: uuid.UUID
    target_soldier_id: uuid.UUID | None = None
    target_soldier_ids: list[uuid.UUID] | None = None
    open_to_marketplace: bool = False
    reason: str | None = Field(default=None, max_length=1000)
```

Replace `ManagerSideRequest` (lines 745-746):

```python
class ManagerSideRequest(BaseModel):
    side: str  # "requester" | "covering"
    candidate_id: uuid.UUID | None = None
```

Rewrite `_out` (lines 196-256) and delete `_out_bulk`/`_side_node_bulk` (lines 596-706, folded into `_out` below — `/swaps/pending` now calls the same `_out`, accepting the N+1 query cost the existing docstring at line 636 already flagged as an acceptable simplification):

```python
def _candidate_out(session: Session, candidate: SwapCandidate) -> SwapCandidateOut:
    soldier = session.get(Soldier, candidate.soldier_id)
    manager_approvals = _manager_approvals_out(session, candidate.swap_request_id, candidate.soldier_id, "covering", candidate_id=candidate.id)
    return SwapCandidateOut(
        id=candidate.id, soldier_id=candidate.soldier_id,
        soldier_name=soldier.full_name if soldier else None,
        source=candidate.source, status=candidate.status,
        soldier_side_approved=candidate.soldier_side_approved,
        offered_assignment_ids=[str(x) for x in (candidate.offered_assignment_ids or [])],
        manager_approvals=manager_approvals,
    )


def _out(r: SwapRequest, session: Session | None = None, warnings: list[str] | None = None) -> SwapOut:
    duty_type_name = None
    duty_location_name = None
    duty_type_id = None
    duty_location_id = None
    duty_start_date = None
    duty_end_date = None
    requesting_soldier_name, requesting_commander_name = _soldier_names(session, r.requesting_soldier_id)  # type: ignore[arg-type]
    requesting_soldier_node_name: str | None = None
    if session is not None:
        req_soldier = session.get(Soldier, r.requesting_soldier_id)
        if req_soldier is not None and req_soldier.hierarchy_node_id is not None:
            node = session.get(HierarchyNode, req_soldier.hierarchy_node_id)
            if node is not None:
                requesting_soldier_node_name = node.name
    duty_shift_id = None
    if session is not None:
        assignment = session.get(DutyAssignment, r.duty_assignment_id)
        if assignment is not None:
            duty_type_id = assignment.duty_type_id
            duty_location_id = assignment.duty_location_id
            duty_start_date = assignment.start_date
            duty_end_date = assignment.end_date
            duty_shift_id = assignment.duty_shift_id
            dt = session.get(DutyType, assignment.duty_type_id)
            loc = session.get(DutyLocation, assignment.duty_location_id)
            duty_type_name = dt.name if dt else None
            duty_location_name = loc.name if loc else None
    requester_manager_approvals = _manager_approvals_out(session, r.id, r.requesting_soldier_id, "requester", candidate_id=None) if session is not None else []
    rejected_by_name = None
    if session is not None and r.rejected_by:
        rejected_by_soldier = session.get(Soldier, r.rejected_by)
        rejected_by_name = rejected_by_soldier.full_name if rejected_by_soldier else None
    candidates_out: list[SwapCandidateOut] = []
    if session is not None:
        candidate_rows = session.execute(
            select(SwapCandidate).where(SwapCandidate.swap_request_id == r.id).order_by(SwapCandidate.created_at.asc())
        ).scalars().all()
        candidates_out = [_candidate_out(session, c) for c in candidate_rows]
    return SwapOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, duty_date=r.duty_date,
        requesting_soldier_id=r.requesting_soldier_id, open_to_marketplace=r.open_to_marketplace,
        status=r.status, reason=r.reason,
        requester_side_approved=r.requester_side_approved,
        decision_note=r.decision_note,
        rejected_by_name=rejected_by_name,
        created_at=r.created_at,
        duty_type_name=duty_type_name, duty_location_name=duty_location_name,
        duty_type_id=duty_type_id, duty_location_id=duty_location_id,
        duty_start_date=duty_start_date, duty_end_date=duty_end_date, duty_shift_id=duty_shift_id,
        warnings=warnings or [],
        requesting_soldier_name=requesting_soldier_name,
        requesting_commander_name=requesting_commander_name,
        requesting_soldier_node_name=requesting_soldier_node_name,
        requester_manager_approvals=requester_manager_approvals,
        candidates=candidates_out,
    )
```

Update `_manager_approvals_out`'s signature (lines 113-193) to accept `candidate_id: uuid.UUID | None` and filter on it instead of just `side`:

```python
def _manager_approvals_out(
    session: Session, request_id: uuid.UUID, soldier_id: uuid.UUID, side: str, *, candidate_id: uuid.UUID | None,
) -> list[SwapManagerApprovalOut]:
    from app.services.approval_scope import commander_chain_for_soldier, duty_manager_chain_for_soldier
    from app.services.swaps import _require_duty_manager_approval

    decisions_by_person_kind = {
        (row.commander_id, row.approver_kind): row
        for row in session.execute(
            select(SwapManagerApproval).where(
                SwapManagerApproval.swap_request_id == request_id,
                SwapManagerApproval.swap_candidate_id == candidate_id,
                SwapManagerApproval.side == side,
            )
        ).scalars().all()
    }
    # (rest of the function body is unchanged — only the query filter above changed)
```

(Copy the rest of the existing function body verbatim below the query — it doesn't reference the removed columns.)

Update every route body:
- `my_swaps`, `board`, `list_swaps_for_assignment`, `pending`: change every `_out_bulk(...)`/`_side_node_bulk`/target/covering-based filter to use the new `_out(r, session)` and query against `SwapCandidate` where the old code filtered on `SwapRequest.target_soldier_id`/`covering_soldier_id`. Specifically:
  - `get_incoming_swap_count` / `list_incoming_swaps`: change the `SwapRequest.target_soldier_id == user.id` filter to a join against `SwapCandidate` (`SwapCandidate.soldier_id == user.id, SwapCandidate.source == "invited"`) — a soldier's "incoming" list is now "requests where I'm an invited candidate still pending," e.g.:
    ```python
    @router.get("/swaps/incoming", response_model=list[SwapOut])
    def list_incoming_swaps(
        session: Session = Depends(get_session),
        user: Soldier = Depends(require_password_changed),
    ) -> list[SwapOut]:
        request_ids = session.execute(
            select(SwapCandidate.swap_request_id).where(
                SwapCandidate.soldier_id == user.id,
                SwapCandidate.source == "invited",
                SwapCandidate.status == "pending",
            )
        ).scalars().all()
        rows = session.execute(
            select(SwapRequest).where(
                SwapRequest.id.in_(request_ids), SwapRequest.status == "open",
            ).order_by(SwapRequest.created_at.desc())
        ).scalars().all()
        return [_out(r, session) for r in rows]
    ```
    Apply the equivalent id-list join for `get_incoming_swap_count`.
  - `board`: replace `list_open_board` in `backend/app/services/swaps.py` (currently lines 173-191) with:
    ```python
    def list_open_board(session: Session, *, for_soldier_id: uuid.UUID) -> list[SwapRequest]:
        """Open postings visible to a soldier: marketplace-visible, excluding
        their own requests and ones they're already a candidate on."""
        already_candidate_on = session.execute(
            select(SwapCandidate.swap_request_id).where(SwapCandidate.soldier_id == for_soldier_id)
        ).scalars().all()
        return list(
            session.execute(
                select(SwapRequest)
                .where(
                    SwapRequest.status == "open",
                    SwapRequest.requesting_soldier_id != for_soldier_id,
                    SwapRequest.open_to_marketplace.is_(True),
                    SwapRequest.id.notin_(already_candidate_on) if already_candidate_on else True,
                )
                .order_by(SwapRequest.duty_date.asc())
            )
            .scalars()
            .all()
        )
    ```
    (The `if already_candidate_on else True` guard avoids passing an empty `IN ()`/`NOT IN ()` list to SQLAlchemy, which some dialects handle awkwardly — same defensive pattern as elsewhere in this codebase's query-building.)
  - `pending`: replace `list_pending_approval` (currently lines 870-879) with:
    ```python
    def list_pending_approval(session: Session) -> list[SwapRequest]:
        request_ids = session.execute(
            select(SwapCandidate.swap_request_id).where(
                SwapCandidate.status.in_(["pending", "accepted"])
            ).distinct()
        ).scalars().all()
        if not request_ids:
            return []
        return list(
            session.execute(
                select(SwapRequest)
                .where(SwapRequest.status == "open", SwapRequest.id.in_(request_ids))
                .order_by(SwapRequest.duty_date.asc())
            )
            .scalars()
            .all()
        )
    ```
    In the route's `pending()` function itself (lines 545-623), the scope-filtering `can(...)` checks currently test one `covering_soldier_id`'s node — change the list comprehension's `or` clause to test every live candidate's node instead of a single one:
    ```python
        roots = scope_root_ids(session, user)
        user_is_commander = is_commander(session, user.id)
        user_is_duty_manager = is_duty_manager(session, user.id)
        def _visible(r: SwapRequest) -> bool:
            if can(
                user, Action.SWAP_APPROVE, target_node=_side_node_bulk(r, r.requesting_soldier_id), roots=roots,
                is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
            ):
                return True
            candidates = session.execute(
                select(SwapCandidate).where(SwapCandidate.swap_request_id == r.id)
            ).scalars().all()
            for candidate in candidates:
                if can(
                    user, Action.SWAP_APPROVE, target_node=_soldier_node(session, candidate.soldier_id), roots=roots,
                    is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
                ):
                    return True
            return False
        return [_out(r, session) for r in all_pending if _visible(r)]
    ```
    This plan follows the codebase's established convention (no SQLAlchemy `relationship()` is used anywhere in `models.py` — every cross-table lookup in this file is an explicit `session.execute(select(...))`) rather than introducing one here.

    Since `_out_bulk`/`_side_node_bulk`'s bulk-preload optimization is being folded away (per this task's earlier instruction to delete `_out_bulk` and reuse `_out`), also delete the standalone bulk-preload block (the `soldiers = {...}`, `nodes = {...}`, etc. dict-building lines currently between `list_pending_approval`'s call and the `if user.role == "admin"` branch) and its `_side_node_bulk` closure entirely. Replace it with a small helper next to `_side_node` (used above as `_soldier_node`):
    ```python
    def _soldier_node(session: Session, soldier_id: uuid.UUID | None) -> HierarchyNode | None:
        if soldier_id is None:
            return None
        soldier = session.get(Soldier, soldier_id)
        if soldier is None or soldier.hierarchy_node_id is None:
            return None
        return session.get(HierarchyNode, soldier.hierarchy_node_id)
    ```
    and use `_soldier_node(session, r.requesting_soldier_id)` in place of the old `_side_node_bulk(r, r.requesting_soldier_id)` call for the requester-node check just above `_visible`'s definition.
- `create`/`create_bulk`: `create` passes `open_to_marketplace=body.open_to_marketplace` through to `svc.create_request(...)` and drops the `first = r[0] if isinstance(r, list) else r` fan-out handling (`create_request` always returns a single `SwapRequest` now, never a list, per Task 2). Remove `/me/swaps/bulk` and the `create_bulk` route function entirely (lines 440-458) — Task 7 already deletes the frontend's `createBulkSwap` wrapper that was its only caller, since `create` now handles both targets and marketplace in one call.
- `soldier_approve`/`soldier_reject`: unchanged signatures — `svc.approve_soldier_side`/`svc.reject_request` (wait: `soldier_reject` currently calls `reject_request`, which now rejects the **whole** parent — for a candidate wanting to decline their own candidacy, it should call `svc.decline_candidate` instead when `user.id != req.requesting_soldier_id`; keep calling `reject_request` only when `user.id == req.requesting_soldier_id`):
  ```python
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
      try:
          if user.id == req.requesting_soldier_id:
              r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
          else:
              svc.decline_candidate(session, request_id=request_id, soldier_id=user.id, actor_id=user.id)
              r = session.get(SwapRequest, request_id)
      except svc.SwapError as exc:
          raise _err(exc) from exc
      session.commit()
      session.refresh(r)
      return _out(r, session)
  ```
- `manager_approve`/`manager_reject`: pass `body.candidate_id` through to `svc.approve_manager_side(...)`/`svc.reject_manager_row(...)`, and update `_side_node` (lines 749-756) to accept a candidate:
  ```python
  def _side_node(session: Session, req: SwapRequest, side: str, candidate_id: uuid.UUID | None) -> HierarchyNode | None:
      if side == "requester":
          soldier_id = req.requesting_soldier_id
      else:
          if candidate_id is None:
              return None
          candidate = session.get(SwapCandidate, candidate_id)
          soldier_id = candidate.soldier_id if candidate else None
      if soldier_id is None:
          return None
      soldier = session.get(Soldier, soldier_id)
      if soldier is None or soldier.hierarchy_node_id is None:
          return None
      return session.get(HierarchyNode, soldier.hierarchy_node_id)
  ```
  and thread `body.candidate_id` through both call sites in `manager_approve`/`manager_reject`.
- `submit_cover_offer`: pass `user.id` as `covering_soldier_id` to the rewritten `svc.cover_offer(...)` from Task 5 (it now resolves the candidate internally, no route-level change needed beyond matching the new service signature).
- Add the import `SwapCandidate` to the `from app.db.models import (...)` line at the top of the file.

Given the size of this task, work through it method-by-method, running the test file after each route group (my_swaps/board/incoming → create/claim → approve/reject → manager-approve/reject) rather than all at once, so failures are localized.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_swaps_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the broader swaps test area for regressions**

Run: `pytest -m swaps -q` (check `pyproject.toml`/`conftest.py` for whether a `swaps` marker exists; if not, run `pytest tests/ -k swap -v` instead)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/swaps.py backend/tests/integration/test_swaps_api.py
git commit -m "feat: rewrite swap routes/schemas around candidates list"
```

---

### Task 7: Frontend — `api/swaps.ts` type + function updates

**Files:**
- Modify: `frontend/src/api/swaps.ts`
- Test: Create `frontend/src/api/swaps.test.ts` if one doesn't exist (check first)

**Interfaces:**
- Consumes: Task 6's `SwapOut`/`SwapCandidateOut` shape.
- Produces: `SwapRequest.candidates: SwapCandidate[]` replacing flat covering fields; `createSwap` gains `open_to_marketplace`; `soldierApproveSwap`/`soldierRejectSwap` unchanged signatures; `managerApproveSwap`/`managerRejectSwap` gain an optional `candidateId`. Consumed by Tasks 8-10.

- [ ] **Step 1: Update the types and functions in `frontend/src/api/swaps.ts`**

This is a pure type/wrapper file with no existing tests of its own (verify with `ls frontend/src/api/swaps.test.ts` first) — apply the changes directly, then verify via the frontend build/typecheck (Step 2) rather than a dedicated unit test, matching this file's existing untested-wrapper convention.

Replace `SwapRequest` (lines 17-46):

```typescript
export interface SwapCandidate {
  id: string;
  soldier_id: string;
  soldier_name: string | null;
  source: "invited" | "marketplace";
  status: "pending" | "declined" | "accepted" | "applied" | "cancelled";
  soldier_side_approved: boolean | null;
  offered_assignment_ids: string[];
  manager_approvals: SwapManagerApproval[];
}

export interface SwapRequest {
  id: string;
  duty_assignment_id: string;
  duty_date: string;
  requesting_soldier_id: string;
  open_to_marketplace: boolean;
  status: "open" | "applied" | "rejected" | "cancelled";
  reason: string | null;
  requester_side_approved: boolean | null;
  decision_note: string | null;
  created_at: string;
  duty_type_name: string | null;
  duty_location_name: string | null;
  duty_type_id: string | null;
  duty_location_id: string | null;
  duty_start_date: string | null;
  duty_end_date: string | null;
  duty_shift_id: string | null;
  warnings?: string[];
  requesting_soldier_name?: string | null;
  requesting_commander_name?: string | null;
  requesting_soldier_node_name?: string | null;
  requester_manager_approvals: SwapManagerApproval[];
  candidates: SwapCandidate[];
}
```

Replace `CreateSwapInput` (lines 48-52):

```typescript
export interface CreateSwapInput {
  duty_assignment_id: string;
  target_soldier_id?: string | null;
  target_soldier_ids?: string[];
  open_to_marketplace?: boolean;
  reason?: string | null;
}
```

Delete `createBulkSwap` (lines 67-71) — its call sites move to a single `createSwap` call in Task 8.

Replace `managerApproveSwap`/`managerRejectSwap` (lines 119-125):

```typescript
export async function managerApproveSwap(id: string, side: "requester" | "covering", candidateId?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/manager-approve`, { side, candidate_id: candidateId ?? null })).data;
}

export async function managerRejectSwap(id: string, decision_note?: string, candidateId?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/manager-reject`, { decision_note, candidate_id: candidateId ?? null })).data;
}
```

- [ ] **Step 2: Typecheck**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: errors in every consumer of the old `SwapRequest` shape (`SwapsPage.tsx`, `ApprovalsPage.tsx`) — this is expected at this point in the plan; confirm the errors are all in those two files and not `swaps.ts` itself, then proceed (Tasks 8-10 fix them).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/swaps.ts
git commit -m "feat: update swaps API types for candidates-list shape"
```

---

### Task 8: Frontend — `AskSwapModal` combined targets + marketplace

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx` (the `AskSwapModal` function, lines 207-334)
- Test: Create `frontend/src/pages/SwapsPage.test.tsx` if one doesn't exist for this modal (check first: `ls frontend/src/pages/SwapsPage.test.tsx`); if none exists, add a minimal one covering just this modal's new combined-submission behavior — full-page tests for the rest of `SwapsPage` are out of scope for this task (covered by Task 9's manual verification).

**Interfaces:**
- Consumes: `createSwap` with `open_to_marketplace` (Task 7).
- Produces: submits one `createSwap` call carrying both `target_soldier_ids` and `open_to_marketplace`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/SwapsPage.test.tsx` (or add to it if it exists):

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

const mockCreateSwap = vi.fn().mockResolvedValue({});
vi.mock("../api/swaps", async () => {
  const actual = await vi.importActual<typeof import("../api/swaps")>("../api/swaps");
  return { ...actual, createSwap: (...args: unknown[]) => mockCreateSwap(...args), listEligibleTargets: vi.fn().mockResolvedValue([]) };
});
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, opts?: Record<string, unknown>) => (opts ? `${k}:${JSON.stringify(opts)}` : k) }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ enrollmentPending: false }) }));
vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-query")>("@tanstack/react-query");
  return actual;
});

// Import after mocks so the module graph picks them up.
import AskSwapModalHarness from "./SwapsPageAskSwapModalHarness"; // see Step 3 note

describe("AskSwapModal combined targets + marketplace", () => {
  test("submitting with both a checked marketplace box and a selected target sends both in one call", async () => {
    // Render harness, check the marketplace checkbox, submit with no targets selected first is invalid;
    // this test's exact DOM interaction depends on the modal's final markup from Step 4 below —
    // write the concrete queries against that markup once it exists, following this file's
    // existing test conventions for other modals (see frontend/src/components/ShiftFormModal.test.tsx
        // for the established pattern of testing a form modal in isolation).
  });
});
```

Since `AskSwapModal` is a non-exported function inside `SwapsPage.tsx`, this task's first real step is deciding whether to export it for direct testing or test it through the full `SwapsPage`. Given the existing codebase convention (check `frontend/src/components/ShiftFormModal.test.tsx` — a standalone modal file, exported and tested directly), the cleaner fix here is to extract `AskSwapModal` into its own file `frontend/src/components/AskSwapModal.tsx` as part of this task (a natural refactor prompted by needing to test it in isolation, not scope creep — it was already a self-contained function taking no `SwapsPage`-internal state). Do that extraction first, updating `SwapsPage.tsx`'s import, then write the test against the standalone file directly instead of a harness — delete the harness approach above once the extraction is done.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/AskSwapModal.test.tsx`
Expected: FAIL — checkbox/combined-submit behavior doesn't exist yet.

- [ ] **Step 3: Extract and rewrite `AskSwapModal`**

Move the function from `SwapsPage.tsx` into `frontend/src/components/AskSwapModal.tsx`, changing the mode radio buttons to independent controls:

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import { createSwap, listEligibleTargets, getSwapConfig, CreateSwapInput } from "../api/swaps";
import { EffectiveDuty } from "../api/assignments";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";

function extractErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail) {
    if (detail.startsWith("cover_not_eligible:")) {
      return detail.slice("cover_not_eligible:".length) || fallback;
    }
  }
  if (Array.isArray(detail)) {
    const fields = (detail as { loc?: string[] }[]).map((d) => d.loc?.slice(1).join(".") ?? "?").join(", ");
    return fields ? `נתונים לא תקינים בשדות: ${fields}` : fallback;
  }
  return translateApiError(err, t, fallback);
}

export default function AskSwapModal({
  duty, dutyTypeName, onClose, onCreated,
}: {
  duty: EffectiveDuty; dutyTypeName: string; onClose: () => void; onCreated: () => void;
}) {
  const { t } = useTranslation();
  const { enrollmentPending } = useAuth();
  const [openToMarketplace, setOpenToMarketplace] = useState(false);
  const [selectedTargets, setSelectedTargets] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const eligibleQuery = useQuery({
    queryKey: ["swaps", "eligible-targets", duty.assignment_id],
    queryFn: () => listEligibleTargets(duty.assignment_id),
  });
  const eligibleTargets = eligibleQuery.data ?? [];
  const configQuery = useQuery({ queryKey: queryKeys.swapConfig(), queryFn: getSwapConfig });
  const maxTargets = configQuery.data?.max_specific_targets ?? 5;

  function toggleTarget(id: string) {
    setSelectedTargets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < maxTargets) next.add(id);
      return next;
    });
  }

  const nothingSelected = selectedTargets.size === 0 && !openToMarketplace;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (nothingSelected) {
      setError(t("swaps.select_at_least_one"));
      return;
    }
    try {
      const input: CreateSwapInput = {
        duty_assignment_id: duty.assignment_id,
        reason: reason || null,
        target_soldier_ids: Array.from(selectedTargets),
        open_to_marketplace: openToMarketplace,
      };
      await createSwap(input);
      onCreated();
    } catch (err: unknown) {
      setError(extractErrorMessage(err, t, "שגיאה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">{t("swaps.ask_swap")}: {dutyTypeName}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3" dir="ltr">
          {(() => {
            const last = lastDutyDay(duty.end_date);
            return duty.start_date === last ? duty.start_date : `${duty.start_date} → ${last}`;
          })()}
        </p>
        {enrollmentPending && (
          <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2">
            בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input
              type="checkbox"
              data-testid="ask-swap-marketplace-checkbox"
              checked={openToMarketplace}
              onChange={(e) => setOpenToMarketplace(e.target.checked)}
            />
            {t("swaps.post_open")}
          </label>
          <div className="space-y-1">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {t("swaps.select_up_to", { n: maxTargets })} ({selectedTargets.size}/{maxTargets})
            </p>
            <div className="max-h-48 overflow-y-auto border rounded dark:border-gray-600">
              {eligibleTargets.length === 0 ? (
                <p className="text-sm text-gray-500 p-2">{t("swaps.no_eligible_targets")}</p>
              ) : (
                <ul>
                  {eligibleTargets.map((s) => (
                    <li key={s.soldier_id} className="flex items-center gap-2 px-2 py-1 border-b last:border-b-0 dark:border-gray-700 text-sm">
                      <input
                        type="checkbox"
                        checked={selectedTargets.has(s.soldier_id)}
                        disabled={!selectedTargets.has(s.soldier_id) && selectedTargets.size >= maxTargets}
                        onChange={() => toggleTarget(s.soldier_id)}
                      />
                      <span>{s.full_name}{s.node_name ? ` — ${s.node_name}` : ""} ({s.hierarchy_distance})</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          <textarea placeholder={t("swaps.personal_message")} value={reason}
            onChange={e => setReason(e.target.value)} rows={3}
            className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300">{t("swaps.cancel")}</button>
            <button type="submit" disabled={enrollmentPending || nothingSelected} className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

Update `SwapsPage.tsx`: delete the old `AskSwapModal` function definition (lines 207-334), add `import AskSwapModal from "../components/AskSwapModal";` near the top, and remove `createBulkSwap` from its import list (Task 7 deleted that function).

Now write `frontend/src/components/AskSwapModal.test.tsx` for real (replacing the harness sketch from Step 1):

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi, beforeEach } from "vitest";
import AskSwapModal from "./AskSwapModal";

const mockCreateSwap = vi.fn().mockResolvedValue({});
vi.mock("../api/swaps", () => ({
  createSwap: (...args: unknown[]) => mockCreateSwap(...args),
  listEligibleTargets: vi.fn().mockResolvedValue([{ soldier_id: "s1", full_name: "Yossi", node_name: null, hierarchy_distance: 1 }]),
  getSwapConfig: vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 }),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ enrollmentPending: false }) }));

function renderModal() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AskSwapModal
        duty={{ assignment_id: "a1", start_date: "2026-08-01", end_date: "2026-08-02" } as never}
        dutyTypeName="Guard"
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("AskSwapModal", () => {
  beforeEach(() => mockCreateSwap.mockClear());

  test("submitting with the marketplace checkbox AND a selected target sends both in one call", async () => {
    renderModal();
    fireEvent.click(await screen.findByTestId("ask-swap-marketplace-checkbox"));
    const targetCheckbox = (await screen.findAllByRole("checkbox"))[1];
    fireEvent.click(targetCheckbox);
    fireEvent.click(screen.getByText("swaps.save"));
    await waitFor(() => expect(mockCreateSwap).toHaveBeenCalledWith(
      expect.objectContaining({ open_to_marketplace: true, target_soldier_ids: ["s1"] }),
    ));
  });

  test("submit is disabled with neither marketplace checked nor a target selected", () => {
    renderModal();
    expect(screen.getByText("swaps.save")).toBeDisabled();
  });
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/AskSwapModal.test.tsx`
Expected: PASS

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit`
Expected: fewer errors than Task 7's checkpoint (this file's consumers fixed); remaining errors should now be confined to the "mine"/"pending" tab rendering and `ApprovalsPage.tsx` (Tasks 9-10).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AskSwapModal.tsx frontend/src/components/AskSwapModal.test.tsx frontend/src/pages/SwapsPage.tsx
git commit -m "feat: extract AskSwapModal, allow combining marketplace + specific targets in one ask"
```

---

### Task 9: Frontend — `SwapsPage` candidate-list rendering (mine + pending tabs)

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx`
- Test: Create `frontend/src/pages/SwapsPage.test.tsx` if Task 8 didn't already create one for a different purpose (check first — if it exists from Task 8's harness sketch, that harness approach was abandoned in favor of the standalone `AskSwapModal.test.tsx`; this task can create the real `SwapsPage.test.tsx` fresh)

**Interfaces:**
- Consumes: `SwapRequest.candidates` (Task 7).
- Produces: `renderMySwapCard` shows a collapsible party list; `PendingApprovalCard` shows one approval block per live candidate.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/SwapsPage.test.tsx`:

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import SwapsPage from "./SwapsPage";
import type { SwapRequest } from "../api/swaps";

const mySwap: SwapRequest = {
  id: "req1", duty_assignment_id: "a1", duty_date: "2026-08-01", requesting_soldier_id: "me",
  open_to_marketplace: true, status: "open", reason: null, requester_side_approved: true,
  decision_note: null, created_at: "2026-07-01T00:00:00Z",
  duty_type_name: "Guard", duty_location_name: "Base", duty_type_id: "dt1", duty_location_id: "l1",
  duty_start_date: "2026-08-01", duty_end_date: "2026-08-02", duty_shift_id: null,
  requesting_soldier_name: "Me", requesting_commander_name: null, requesting_soldier_node_name: null,
  requester_manager_approvals: [],
  candidates: [
    { id: "c1", soldier_id: "s1", soldier_name: "Yossi", source: "invited", status: "pending", soldier_side_approved: null, offered_assignment_ids: [], manager_approvals: [] },
    { id: "c2", soldier_id: "s2", soldier_name: "Dana", source: "marketplace", status: "accepted", soldier_side_approved: true, offered_assignment_ids: [], manager_approvals: [] },
  ],
};

vi.mock("../api/swaps", async () => {
  const actual = await vi.importActual<typeof import("../api/swaps")>("../api/swaps");
  return {
    ...actual,
    listMySwaps: vi.fn().mockResolvedValue([mySwap]),
    listBoard: vi.fn().mockResolvedValue([]),
    listIncomingSwaps: vi.fn().mockResolvedValue([]),
    getSwapConfig: vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 }),
  };
});
vi.mock("../api/assignments", () => ({ listEffectiveDuties: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/dutyConfig", () => ({ listDutyTypes: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/hierarchy", () => ({ fetchTree: vi.fn().mockResolvedValue([]) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: "me", role: "soldier", is_commander: false, is_duty_manager: false } }) }));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SwapsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SwapsPage mine tab candidate list", () => {
  test("shows one card per request with both candidates listed, not one card per candidate", async () => {
    renderPage();
    expect(await screen.findByText("Yossi")).toBeInTheDocument();
    expect(await screen.findByText("Dana")).toBeInTheDocument();
    // Exactly one duty header/date rendered for this request, proving it's
    // one card, not two — SwapDutyHeader renders the duty_type_name once per card.
    expect(screen.getAllByText("Guard")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/SwapsPage.test.tsx`
Expected: FAIL — current `renderMySwapCard` doesn't render `swap.candidates` at all (references removed `covering_soldier_id` etc., likely a type error before it even gets to a runtime assertion — that's fine, confirms the rewrite is needed).

- [ ] **Step 3: Rewrite `renderMySwapCard` and `PendingApprovalCard`/`PendingSide` in `SwapsPage.tsx`**

Add a new component after `ApprovalStatus` (previously ending around line 205):

```typescript
function CandidateRow({ candidate, requireManagerApproval, requireDutyManagerApproval, t }: {
  candidate: SwapRequest["candidates"][number];
  requireManagerApproval: boolean; requireDutyManagerApproval: boolean;
  t: (k: string) => string;
}) {
  const groups = groupByKind(candidate.manager_approvals);
  const sourceLabel = candidate.source === "marketplace" ? t("swaps.candidate_source_marketplace") : t("swaps.candidate_source_invited");
  return (
    <div className="border rounded p-2 text-xs space-y-1 dark:border-gray-600">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium dark:text-gray-100">{candidate.soldier_name ?? candidate.soldier_id.slice(0, 8)}</span>
        <span className="text-gray-400">{sourceLabel}</span>
      </div>
      <ApprovalBadge value={candidate.soldier_side_approved} t={t} />
      {requireManagerApproval && candidate.status === "accepted" && (
        <div className="text-gray-500 dark:text-gray-400 space-y-0.5">
          <div>{t("swaps.approver_kind_commander")}: <DirectCommanderApproval approvals={groups.commander} /></div>
          {requireDutyManagerApproval && (
            <div>{t("swaps.approver_kind_duty_manager")}: <DirectCommanderApproval approvals={groups.duty_manager} /></div>
          )}
        </div>
      )}
      {candidate.status === "declined" && <p className="text-red-500">{t("swaps.candidate_declined")}</p>}
      {candidate.status === "cancelled" && <p className="text-gray-400">{t("swaps.candidate_cancelled")}</p>}
      {candidate.status === "applied" && <p className="text-green-600">{t("swaps.candidate_applied")}</p>}
    </div>
  );
}
```

Replace `renderMySwapCard` (lines 487-527):

```typescript
  const renderMySwapCard = (swap: SwapRequest) => (
    <li key={swap.id} className="border rounded p-3 text-sm space-y-1.5 dark:border-gray-600">
      <div className="flex items-start justify-between gap-2">
        <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
        <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
          {t(statusKey(swap.status))}
        </span>
      </div>
      {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
      {swap.decision_note && (
        <p className="text-xs text-amber-600 dark:text-amber-400">{t("swaps.decision_note")}: {swap.decision_note}</p>
      )}
      {swap.candidates.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{t("swaps.candidates_title")} ({swap.candidates.length})</p>
          <div className="space-y-1">
            {swap.candidates.map((c) => (
              <CandidateRow key={c.id} candidate={c} requireManagerApproval={requireManagerApproval} requireDutyManagerApproval={requireDutyManagerApproval} t={t} />
            ))}
          </div>
        </div>
      )}
      {swap.status === "open" && (
        <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
          {t("swaps.cancel")}
        </button>
      )}
    </li>
  );
```

Replace `PendingSide`/`PendingApprovalCard` (lines 84-146) — the "pending" tab (tab 3) now shows one card per request, one `CandidateRow`-style block per **live** candidate the current user is either the requester of or a candidate on, instead of a fixed two-column requester/covering layout:

```typescript
function PendingApprovalCard({
  swap, requireManagerApproval, requireDutyManagerApproval, onShiftClick, t,
}: {
  swap: SwapRequest; requireManagerApproval: boolean; requireDutyManagerApproval: boolean;
  onShiftClick?: () => void; t: (k: string) => string;
}) {
  const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
  return (
    <li className="border rounded-lg p-4 space-y-3 dark:border-gray-600">
      <SwapDutyHeader swap={swap} onShiftClick={onShiftClick} />
      <div className="flex flex-wrap gap-3">
        <div className="flex-1 min-w-[140px] border rounded p-3 space-y-1.5 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/40">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">{t("swaps.side_requester")}</p>
          <p className="text-sm font-medium dark:text-gray-100 truncate">{swap.requesting_soldier_name ?? "—"}</p>
          <ApprovalBadge value={swap.requester_side_approved} t={t} />
        </div>
        {liveCandidates.map((c) => (
          <div key={c.id} className="flex-1 min-w-[140px]">
            <CandidateRow candidate={c} requireManagerApproval={requireManagerApproval} requireDutyManagerApproval={requireDutyManagerApproval} t={t} />
          </div>
        ))}
      </div>
    </li>
  );
}
```

Remove the now-unused `PendingSide` function entirely, and remove `ApprovalStatus`'s references to the deleted `covering_side_approved`/`covering_manager_approvals` fields (rewrite `ApprovalStatus`, lines 180-205, to only show the requester side plus a summary count of live candidates — e.g. `t("swaps.n_candidates_pending", { n: liveCandidates.length })` — since per-candidate detail now lives in `CandidateRow` within the card body, not a separate status block).

Update the `mySwaps`/`renderMySwapCard` call sites and the `renderIncomingCard`/`renderBoardCard` functions (which reference `swap.requesting_soldier_id`/`swap.reason` etc. — those still exist on the parent, no change needed there) — read them once more after this edit to confirm no leftover references to removed fields (`grep -n "covering_soldier_id\|target_soldier_id\|covering_side_approved\|covering_manager_approvals" frontend/src/pages/SwapsPage.tsx` should return nothing when done).

Add the new i18n keys this task introduces to `frontend/src/i18n/he.json` under `"swaps"`: `candidates_title`, `candidate_source_marketplace`, `candidate_source_invited`, `candidate_declined`, `candidate_cancelled`, `candidate_applied`, `n_candidates_pending` (with a Hebrew value for each, e.g. `"candidates_title": "מועמדים"`, `"candidate_source_marketplace": "מהלוח הפתוח"`, `"candidate_source_invited": "הוזמן"`, `"candidate_declined": "סירב"`, `"candidate_cancelled": "בוטל"`, `"candidate_applied": "בוצע"`, `"n_candidates_pending": "{{n}} מועמדים ממתינים"`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/SwapsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit`
Expected: remaining errors confined to `ApprovalsPage.tsx` (Task 10).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/pages/SwapsPage.test.tsx frontend/src/i18n/he.json
git commit -m "feat: render one card per swap request with a per-candidate party list"
```

---

### Task 10: Frontend — `ApprovalsPage` per-candidate swap approval rendering

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Test: `frontend/src/pages/ApprovalsPage.test.tsx` (check if it exists first; extend it if so)

**Interfaces:**
- Consumes: `SwapRequest.candidates` (Task 7), `managerApproveSwap`/`managerRejectSwap` with `candidateId` (Task 7).

- [ ] **Step 1: Write the failing test**

Check `ls frontend/src/pages/ApprovalsPage.test.tsx` first. Add (to the existing file, matching its established mocking conventions for `listPendingSwaps` etc., or create fresh if none exists):

```typescript
test("shows one approval block per live candidate on a swap with multiple candidates", async () => {
  // Mock listPendingSwaps to return one SwapRequest with two candidates
  // (one "invited"/pending, one "accepted" with manager_approvals), switch
  // to the swaps tab, and assert both candidates' names render with
  // independent approve buttons — following this file's existing test
  // setup pattern for the swaps tab (read the existing swap-tab test(s) in
  // this file first, if any, to match fixture conventions exactly).
});
```

Write this fully once you've read the existing test file's swap-tab fixtures (if any) — do not leave it as a comment-only placeholder.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/ApprovalsPage.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Rewrite the swaps tab section in `ApprovalsPage.tsx`**

Replace the `tab === "swaps"` block (lines 597-671):

```typescript
        {tab === "swaps" && (
          <div className="space-y-3" dir="rtl">
            {swapItems.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.none")}</p>}
            {swapItems.map(swap => {
              const isAdmin = user?.role === "admin";
              const reqGroups = groupByKind(swap.requester_manager_approvals);
              const canActCommander = (commanderApprovals: DirectCommanderApprovalRow[]) =>
                isAdmin || commanderApprovals.some(a => a.commander_id === user?.id);
              const canActDutyManager = isAdmin || !!user?.is_duty_manager;
              const liveCandidates = swap.candidates.filter(c => c.status === "pending" || c.status === "accepted");
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong>{t("swaps.requester")}:</strong>
                    <span><SoldierLink id={swap.requesting_soldier_id} name={swap.requesting_soldier_name || swap.requesting_soldier_id.slice(0, 8)} /></span>
                    {swap.requesting_soldier_node_name && <span className="text-xs text-gray-400">{swap.requesting_soldier_node_name}</span>}
                    <ApprovalDotInline value={swap.requester_side_approved} />
                  </div>
                  <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
                  <div className="text-xs text-gray-500 space-y-1">
                    <SwapKindApproval
                      approvals={reqGroups.commander}
                      label={`${t("swaps.requester_managers")} (${t("swaps.approver_kind_commander")})`}
                      canAct={canActCommander(reqGroups.commander)}
                      onApprove={() => onSwapManagerApprove(swap.id, "requester")}
                      t={t}
                    />
                    <SwapKindApproval
                      approvals={reqGroups.duty_manager}
                      label={`${t("swaps.requester_managers")} (${t("swaps.approver_kind_duty_manager")})`}
                      canAct={canActDutyManager}
                      onApprove={() => onSwapManagerApprove(swap.id, "requester")}
                      t={t}
                    />
                  </div>
                  {liveCandidates.length > 0 && (
                    <div className="space-y-2 border-t pt-2 dark:border-gray-700">
                      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{t("swaps.candidates_title")} ({liveCandidates.length})</p>
                      {liveCandidates.map(candidate => {
                        const covGroups = groupByKind(candidate.manager_approvals);
                        return (
                          <div key={candidate.id} className="border rounded p-2 space-y-1">
                            <div className="flex items-center gap-2">
                              <SoldierLink id={candidate.soldier_id} name={candidate.soldier_name || candidate.soldier_id.slice(0, 8)} />
                              <ApprovalDotInline value={candidate.soldier_side_approved} />
                            </div>
                            <div className="text-xs text-gray-500 space-y-1">
                              <SwapKindApproval
                                approvals={covGroups.commander}
                                label={`${t("swaps.covering_managers")} (${t("swaps.approver_kind_commander")})`}
                                canAct={canActCommander(covGroups.commander)}
                                onApprove={() => onSwapManagerApprove(swap.id, "covering", candidate.id)}
                                t={t}
                              />
                              <SwapKindApproval
                                approvals={covGroups.duty_manager}
                                label={`${t("swaps.covering_managers")} (${t("swaps.approver_kind_duty_manager")})`}
                                canAct={canActDutyManager}
                                onApprove={() => onSwapManagerApprove(swap.id, "covering", candidate.id)}
                                t={t}
                              />
                            </div>
                            <div className="flex gap-2 items-center flex-wrap">
                              <input
                                placeholder={t("approvals.decision_note")}
                                value={swapRejectNotes[`${swap.id}:${candidate.id}`] ?? ""}
                                onChange={e => setSwapRejectNotes(prev => ({ ...prev, [`${swap.id}:${candidate.id}`]: e.target.value }))}
                                className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                              />
                              <button
                                onClick={() => onSwapManagerReject(swap.id, candidate.id)}
                                className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                              >
                                {t("approvals.reject")}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
```

Update `onSwapManagerApprove`/`onSwapManagerReject` (previously lines 294-317) to thread an optional `candidateId`:

```typescript
  async function onSwapManagerApprove(id: string, side: "requester" | "covering", candidateId?: string) {
    try {
      await managerApproveSwap(id, side, candidateId);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onSwapManagerReject(id: string, candidateId?: string) {
    const noteKey = candidateId ? `${id}:${candidateId}` : id;
    try {
      await managerRejectSwap(id, swapRejectNotes[noteKey], candidateId);
      const next = { ...swapRejectNotes };
      delete next[noteKey];
      setSwapRejectNotes(next);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
```

Note the top-level requester-side "reject the whole thing" action that existed in the old flat card (the `swapRejectNotes[swap.id]` input + button at the very bottom of the old block) is now folded into the requester-side reject with no `candidateId` — if the design still wants a single "kill the whole request" control separate from per-candidate rejection, add one more button block using `onSwapManagerReject(swap.id)` (no candidateId) near the requester section; include it if a reviewer flags its absence as a regression, since the original UI did expose exactly this action.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/ApprovalsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Typecheck and lint**

Run: `npx tsc --noEmit` then `npm run lint`
Expected: both clean — this is the last frontend task, so this should be the first point where the whole frontend typechecks cleanly again.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "feat: show per-candidate approval progress in the approvals swap tab"
```

---

### Task 11: Manual verification in the browser

**Files:** none (verification only).

- [ ] **Step 1: Start the dev stack**

Run `.\dev.ps1` from the repo root, or confirm a dev server is already up. Log in as a soldier with an upcoming published duty.

- [ ] **Step 2: Verify combined ask**

Go to Swaps → ask to swap a duty → check "post to marketplace" AND select 2 specific soldiers → submit. Confirm exactly one request appears under "mine" (not 3), showing 2 invited candidates plus marketplace visibility.

- [ ] **Step 3: Verify no duplicate request for the same duty**

Try asking to swap the *same* duty again while the first request is still open. Confirm it's rejected with a clear error (surfaces the `already_pending` error).

- [ ] **Step 4: Verify parallel candidate approval**

As a different logged-in soldier (or via a second browser profile), claim the open marketplace posting from the "board" tab. Confirm the original requester's "mine" card now shows both the invited candidates (still pending) and the new marketplace claimant (accepted), without the invited candidates being cancelled.

- [ ] **Step 5: Verify commander approval races correctly**

Log in as the commander/duty-manager for both the requester and at least one candidate. Approve one candidate's commander/duty-manager requirement fully (both sides). Confirm the request finalizes (`applied`), the approved candidate's status becomes `applied`, and every other live candidate becomes `cancelled` with a notification.

- [ ] **Step 6: Verify decline doesn't affect siblings**

Repeat with 2 invited candidates; have one decline via `/me/swaps/{id}/reject` while pending. Confirm the request stays `open` and the other candidate is unaffected.

---

## Self-Review

**Spec coverage:**
- One row per (requester, duty), enforced via DB partial unique index — Task 1. ✓
- Combined targeted + marketplace on one request — Tasks 2, 8. ✓
- Parallel candidates, first-fully-approved-wins finalize race, losers cancelled — Task 4. ✓
- Shared requester-side approval, per-candidate covering-side approval/chain — Tasks 3, 4. ✓
- Candidate decline doesn't affect siblings; requester reject/cancel cascades to all — Tasks 4, 5. ✓
- `take_free`/`cover_offer` adapted without behavior change — Task 5. ✓
- API shape: `SwapOut.candidates`, combined create body, candidate-scoped manager actions — Task 6. ✓
- Frontend: combined ask modal, one card per request with party list, per-candidate approval UI on both `SwapsPage` and `ApprovalsPage` — Tasks 8, 9, 10. ✓
- No Telegram bot changes needed — confirmed by reading `backend/bot/actions.py`, noted in Global Constraints. ✓
- Manual verification of the full race end-to-end — Task 11. ✓

**Placeholder scan:** Task 5's `cover_offer` step and Task 6's `list_open_board`/`list_pending_approval` adaptations intentionally direct the implementer to read the current code first rather than guessing its body from this plan — this is a deliberate "read before you edit" instruction, not a placeholder for missing design; the desired end-state behavior is fully specified in prose immediately alongside each. Task 8/10's test-writing steps similarly ask the implementer to match established per-file test conventions rather than duplicating fixture boilerplate not yet visible to this plan's author — the *assertions* required are stated concretely, not left as TBDs.

**Type consistency:** `SwapCandidate` (model, Task 1) → `SwapCandidateOut` (schema, Task 6) → `SwapCandidate` (frontend type, Task 7) → consumed identically in `CandidateRow` (Task 9) and the `ApprovalsPage` swap tab (Task 10). `candidate_id: uuid.UUID | None` threads consistently through `is_chain_commander_for_side` → `_qualifying_rows_for_actor` → `_get_or_create_row` → `approve_manager_row`/`reject_manager_row`/`approve_manager_side`/`approve_manager_side_override` (Task 4) → route bodies (Task 6) → `managerApproveSwap`/`managerRejectSwap(candidateId?)` (Task 7) → `onSwapManagerApprove`/`onSwapManagerReject` (Task 10).
