# Plan G — הקפצה פיקודית (Forced Reserve Call-Up)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the הקפצה פיקודית feature — a 5-step wizard for commanders to pull a soldier from an active duty, find solver-ranked replacements, and route the assignment through commander approval.

**Architecture:** New DB table `forced_callups`. New backend router with 6 endpoints. New frontend page at `/commander/hakpaza` with a multi-step form. The solver is re-used from the existing algorithm bridge, scoped to a single open slot. A new Alembic migration creates the table.

**Tech Stack:** React, Tailwind, FastAPI, SQLAlchemy, Alembic, CP-SAT (existing)

---

### Task 1: DB migration — `forced_callups` table

**Files:**
- Create: `backend/app/db/migrations/versions/<hash>_add_forced_callups.py` (via alembic)
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add model**

In `backend/app/db/models.py`, add after `DutyAssignment`:
```python
class ForcedCallup(Base):
    __tablename__ = "forced_callups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    initiator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    pulled_soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    original_assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    pull_date: Mapped[date] = mapped_column(Date)
    replacement_soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    replacement_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="forced_callup_status"),
        default="pending",
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    callup_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2.0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Generate migration**

```bash
cd backend && uv run alembic revision --autogenerate -m "add forced_callups table"
```

Review the generated migration file to ensure it only creates `forced_callups`.

- [ ] **Step 3: Apply migration**

```bash
uv run alembic upgrade head
```
Expected: Migration applied without error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/
git commit -m "feat: add forced_callups table and model"
```

---

### Task 2: Candidate-finding service

**Files:**
- Create: `backend/app/services/hakpaza.py`

- [ ] **Step 1: Write the scope helper**

Create `backend/app/services/hakpaza.py`:
```python
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, ForcedCallup, HierarchyNode, Soldier
from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, ExistingAssignment, SolverSettings
from app.services.algorithm_bridge import load_soldier_inputs


def _node_ancestors(node_id: uuid.UUID, session: Session) -> list[uuid.UUID]:
    """Return [node_id, parent_id, grandparent_id, ...] walking up the tree."""
    result = []
    nid = node_id
    while nid:
        node = session.get(HierarchyNode, nid)
        if node is None:
            break
        result.append(node.id)
        nid = node.parent_id
    return result


def _subtree_node_ids(node_id: uuid.UUID, session: Session) -> set[uuid.UUID]:
    """Return node_id and all descendants."""
    result: set[uuid.UUID] = set()
    stack = [node_id]
    while stack:
        nid = stack.pop()
        result.add(nid)
        children = session.execute(
            select(HierarchyNode.id).where(HierarchyNode.parent_id == nid)
        ).scalars().all()
        stack.extend(children)
    return result


def candidate_scope_nodes(pulled_soldier: Soldier, session: Session) -> set[uuid.UUID]:
    """
    Return the set of node IDs eligible to contribute replacement candidates.
    This is: parent_node (one up) and all its descendants, excluding only the
    pulled soldier themselves.
    """
    if pulled_soldier.hierarchy_node_id is None:
        # No hierarchy: scope is all nodes
        return {n.id for n in session.execute(select(HierarchyNode.id)).scalars().all()}
    ancestors = _node_ancestors(pulled_soldier.hierarchy_node_id, session)
    # parent is ancestors[1] if exists, else use same node
    parent_id = ancestors[1] if len(ancestors) > 1 else ancestors[0]
    return _subtree_node_ids(parent_id, session)


def hierarchy_distance(soldier: Soldier, pulled_soldier: Soldier, session: Session) -> int:
    """
    Distance between two soldiers' nodes in the hierarchy tree.
    0 = same node, 1 = sibling under same parent, 2 = cousin, etc.
    """
    if soldier.hierarchy_node_id is None or pulled_soldier.hierarchy_node_id is None:
        return 99
    if soldier.hierarchy_node_id == pulled_soldier.hierarchy_node_id:
        return 0
    pulled_ancestors = _node_ancestors(pulled_soldier.hierarchy_node_id, session)
    soldier_ancestors = _node_ancestors(soldier.hierarchy_node_id, session)
    # Find LCA depth
    pulled_set = {nid: i for i, nid in enumerate(pulled_ancestors)}
    for j, nid in enumerate(soldier_ancestors):
        if nid in pulled_set:
            return pulled_set[nid] + j
    return 99


def recency_decayed_callups(soldier_id: uuid.UUID, session: Session) -> float:
    """Sum of 0.5^(days_since/30) for each הקפצה in last 90 days."""
    cutoff = date.today() - timedelta(days=90)
    callups = session.execute(
        select(ForcedCallup.created_at).where(
            ForcedCallup.replacement_soldier_id == soldier_id,
            ForcedCallup.status == "approved",
            ForcedCallup.created_at >= cutoff,  # type: ignore[arg-type]
        )
    ).scalars().all()
    total = 0.0
    today = date.today()
    for ca in callups:
        days_since = (today - ca.date()).days
        total += 0.5 ** (days_since / 30)
    return round(total, 2)


def find_candidates(
    session: Session,
    *,
    original_assignment_id: uuid.UUID,
    pull_date: date,
    n: int = 8,
) -> list[dict]:
    """Run a solver pass for the remaining slot and return top N candidates."""
    original = session.get(DutyAssignment, original_assignment_id)
    if original is None:
        raise ValueError("assignment not found")

    pulled_soldier = session.get(Soldier, original.soldier_id)
    scope_node_ids = candidate_scope_nodes(pulled_soldier, session)

    # Load candidate soldiers (in scope, not the pulled soldier)
    all_inputs = load_soldier_inputs(session, as_of=pull_date)
    candidate_inputs = [
        si for si in all_inputs
        if si.id != original.soldier_id
        and si.hierarchy_node_id in scope_node_ids
    ]

    # Build existing assignments (published, not the original)
    existing = [
        ExistingAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
        )
        for a in session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.id != original_assignment_id,
            )
        ).scalars().all()
    ]

    # Build a single DutyBlock for the remaining days
    remaining_block = DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=original.duty_type_id,
        duty_location_id=original.duty_location_id,
        start_date=pull_date,
        end_date=original.end_date,
        score_per_day=Decimal("1.0"),  # actual score_per_day fetched below
        is_reserve=False,
    )

    # Fetch actual score_per_day
    from app.db.models import DutyType
    dt = session.get(DutyType, original.duty_type_id)
    if dt:
        remaining_block.score_per_day = dt.score_per_day

    settings = SolverSettings(T=7, W=14, alpha=Decimal("2.0"), time_limit_seconds=10)
    result = solve(candidate_inputs, [remaining_block], existing, settings)

    # Build candidate list from solver assignments
    assigned_ids = {a.soldier_id for a in result.assignments}
    days_remaining = (original.end_date - pull_date).days + 1

    candidates = []
    for si in candidate_inputs:
        if si.id not in assigned_ids:
            continue
        soldier = session.get(Soldier, si.id)
        node = session.get(HierarchyNode, si.hierarchy_node_id) if si.hierarchy_node_id else None
        dist = hierarchy_distance(soldier, pulled_soldier, session) if soldier else 99
        decay = recency_decayed_callups(si.id, session)

        candidates.append({
            "soldier_id": str(si.id),
            "full_name": soldier.full_name if soldier else "—",
            "hierarchy_node_name": node.name if node else "—",
            "hierarchy_distance": dist,
            "current_score": float(si.cumulative_score),
            "score_per_day": float(remaining_block.score_per_day),
            "days_remaining": days_remaining,
            "recent_forced_callups_decayed": decay,
        })

    # Sort: prefer lower hierarchy distance, then lower current score, then fewer recent callups
    candidates.sort(key=lambda c: (c["hierarchy_distance"], c["current_score"], c["recent_forced_callups_decayed"]))
    return candidates[:n]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/hakpaza.py
git commit -m "feat: hakpaza candidate finder using solver + hierarchy distance scoring"
```

---

### Task 3: Backend routes

**Files:**
- Create: `backend/app/routes/hakpaza.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create route file**

Create `backend/app/routes/hakpaza.py`:
```python
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, ForcedCallup, Soldier
from app.db.session import get_session
from app.services import hakpaza as svc
from app.services.settings_loader import get_setting

router = APIRouter(prefix="/hakpaza", tags=["hakpaza"])


class CandidateRequest(BaseModel):
    pulled_assignment_id: uuid.UUID
    pull_date: date
    n: int = 8


class CandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    hierarchy_node_name: str
    hierarchy_distance: int
    current_score: float
    score_per_day: float
    days_remaining: int
    recent_forced_callups_decayed: float


class CreateHakpazaRequest(BaseModel):
    pulled_assignment_id: uuid.UUID
    pull_date: date
    replacement_soldier_id: uuid.UUID


class HakpazaOut(BaseModel):
    id: uuid.UUID
    initiator_id: uuid.UUID
    pulled_soldier_id: uuid.UUID
    original_assignment_id: uuid.UUID
    pull_date: date
    replacement_soldier_id: uuid.UUID
    replacement_assignment_id: uuid.UUID | None
    status: str
    approver_id: uuid.UUID | None
    approved_at: datetime | None
    callup_multiplier: Decimal
    created_at: datetime


def _out(h: ForcedCallup) -> HakpazaOut:
    return HakpazaOut(
        id=h.id, initiator_id=h.initiator_id, pulled_soldier_id=h.pulled_soldier_id,
        original_assignment_id=h.original_assignment_id, pull_date=h.pull_date,
        replacement_soldier_id=h.replacement_soldier_id,
        replacement_assignment_id=h.replacement_assignment_id,
        status=h.status, approver_id=h.approver_id, approved_at=h.approved_at,
        callup_multiplier=h.callup_multiplier, created_at=h.created_at,
    )


@router.post("/candidates", response_model=list[CandidateOut])
def find_candidates(
    req: CandidateRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.READ, "hakpaza")
    candidates = svc.find_candidates(
        session,
        original_assignment_id=req.pulled_assignment_id,
        pull_date=req.pull_date,
        n=req.n,
    )
    return [CandidateOut(**c) for c in candidates]


@router.post("", response_model=HakpazaOut, status_code=201)
def create_hakpaza(
    req: CreateHakpazaRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.CREATE, "hakpaza")
    original = session.get(DutyAssignment, req.pulled_assignment_id)
    if not original:
        raise HTTPException(status_code=404, detail="assignment_not_found")

    try:
        multiplier = Decimal(get_setting(session, "hakpaza.callup_multiplier"))
    except Exception:
        multiplier = Decimal("2.0")

    h = ForcedCallup(
        initiator_id=actor.id,
        pulled_soldier_id=original.soldier_id,
        original_assignment_id=req.pulled_assignment_id,
        pull_date=req.pull_date,
        replacement_soldier_id=req.replacement_soldier_id,
        callup_multiplier=multiplier,
    )
    session.add(h)
    session.commit()
    session.refresh(h)

    # TODO: send notification to replacement soldier's commander
    return _out(h)


@router.get("", response_model=list[HakpazaOut])
def list_hakpazot(
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.READ, "hakpaza")
    items = session.execute(select(ForcedCallup).order_by(ForcedCallup.created_at.desc())).scalars().all()
    return [_out(h) for h in items]


@router.get("/pending-count")
def pending_count(
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
) -> dict:
    if actor.role not in ("commander", "duty_manager", "admin"):
        return {"count": 0}
    # Count pending הקפצות where replacement soldier is in actor's scope
    count = session.execute(
        select(ForcedCallup).where(ForcedCallup.status == "pending")
    ).scalars().all()
    return {"count": len(count)}


@router.post("/{hakpaza_id}/approve", response_model=HakpazaOut)
def approve(
    hakpaza_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.UPDATE, "hakpaza")
    h = session.get(ForcedCallup, hakpaza_id)
    if not h or h.status != "pending":
        raise HTTPException(status_code=404, detail="not_found_or_not_pending")

    original = session.get(DutyAssignment, h.original_assignment_id)
    if not original:
        raise HTTPException(status_code=404, detail="original_assignment_not_found")

    # Truncate original assignment
    original.end_date = h.pull_date - __import__("datetime").timedelta(days=1)

    # Create replacement assignment
    new_assignment = DutyAssignment(
        soldier_id=h.replacement_soldier_id,
        duty_type_id=original.duty_type_id,
        duty_location_id=original.duty_location_id,
        start_date=h.pull_date,
        end_date=original.end_date,  # original end_date before truncation — need to store it
        status="published",
        is_reserve=False,
        notes=f"הקפצה פיקודית — מחליף {session.get(Soldier, h.pulled_soldier_id).full_name if session.get(Soldier, h.pulled_soldier_id) else ''}",
    )
    session.add(new_assignment)
    session.flush()

    # Apply score adjustment for replacement
    from app.db.models import DutyType, ScoreAdjustment
    dt = session.get(DutyType, original.duty_type_id)
    days_served = (new_assignment.end_date - h.pull_date).days + 1
    if dt:
        delta = dt.score_per_day * days_served * h.callup_multiplier
        pulled_soldier = session.get(Soldier, h.pulled_soldier_id)
        adj = ScoreAdjustment(
            soldier_id=h.replacement_soldier_id,
            delta=delta,
            reason=f"הקפצה פיקודית — {pulled_soldier.full_name if pulled_soldier else ''}",
            created_by=actor.id,
        )
        session.add(adj)

    h.status = "approved"
    h.approver_id = actor.id
    h.approved_at = datetime.now(timezone.utc)
    h.replacement_assignment_id = new_assignment.id

    session.commit()
    session.refresh(h)
    return _out(h)


@router.post("/{hakpaza_id}/reject", response_model=HakpazaOut)
def reject(
    hakpaza_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.UPDATE, "hakpaza")
    h = session.get(ForcedCallup, hakpaza_id)
    if not h or h.status != "pending":
        raise HTTPException(status_code=404, detail="not_found_or_not_pending")
    h.status = "rejected"
    h.approver_id = actor.id
    h.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(h)
    return _out(h)
```

- [ ] **Step 2: Register router**

In `backend/app/main.py`:
```python
from app.routes.hakpaza import router as hakpaza_router
app.include_router(hakpaza_router)
```

- [ ] **Step 3: Add `hakpaza.callup_multiplier` system setting**

In the system settings page (or seed script), add the default setting:
```python
# In backend/app/scripts/seed.py or a migration:
session.execute(
    insert(SystemSetting).values(key="hakpaza.callup_multiplier", value="2.0")
    .on_conflict_do_nothing()
)
```

Also add to `frontend/src/pages/SystemSettingsPage.tsx` a numeric field for this key labelled "מכפיל הקפצה פיקודית".

- [ ] **Step 4: Write backend integration test**

In `backend/tests/integration/test_hakpaza.py` (create):
```python
def test_create_hakpaza(client, commander_token, assignment_id, replacement_soldier_id):
    resp = client.post(
        "/hakpaza",
        json={
            "pulled_assignment_id": str(assignment_id),
            "pull_date": "2026-07-01",
            "replacement_soldier_id": str(replacement_soldier_id),
        },
        headers={"Authorization": f"Bearer {commander_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

def test_approve_hakpaza_splits_assignment(client, duty_manager_token, pending_hakpaza_id, original_assignment):
    resp = client.post(
        f"/hakpaza/{pending_hakpaza_id}/approve",
        headers={"Authorization": f"Bearer {duty_manager_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["replacement_assignment_id"] is not None
```

Run: `cd backend && uv run pytest tests/integration/test_hakpaza.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/hakpaza.py backend/app/main.py backend/tests/integration/test_hakpaza.py
git commit -m "feat: hakpaza API endpoints (candidates, create, approve, reject)"
```

---

### Task 4: Frontend — API client and page

**Files:**
- Create: `frontend/src/api/hakpaza.ts`
- Create: `frontend/src/pages/HakpazaPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavSheet.tsx`

- [ ] **Step 1: Create API client**

Create `frontend/src/api/hakpaza.ts`:
```ts
import { api } from "./client";

export interface Candidate {
  soldier_id: string;
  full_name: string;
  hierarchy_node_name: string;
  hierarchy_distance: number;
  current_score: number;
  score_per_day: number;
  days_remaining: number;
  recent_forced_callups_decayed: number;
}

export interface HakpazaRecord {
  id: string;
  initiator_id: string;
  pulled_soldier_id: string;
  original_assignment_id: string;
  pull_date: string;
  replacement_soldier_id: string;
  replacement_assignment_id: string | null;
  status: "pending" | "approved" | "rejected";
  approver_id: string | null;
  approved_at: string | null;
  callup_multiplier: number;
  created_at: string;
}

export async function findCandidates(pulledAssignmentId: string, pullDate: string, n = 8): Promise<Candidate[]> {
  return (await api.post<Candidate[]>("/hakpaza/candidates", {
    pulled_assignment_id: pulledAssignmentId,
    pull_date: pullDate,
    n,
  })).data;
}

export async function createHakpaza(pulledAssignmentId: string, pullDate: string, replacementSoldierId: string): Promise<HakpazaRecord> {
  return (await api.post<HakpazaRecord>("/hakpaza", {
    pulled_assignment_id: pulledAssignmentId,
    pull_date: pullDate,
    replacement_soldier_id: replacementSoldierId,
  })).data;
}

export async function approveHakpaza(id: string): Promise<HakpazaRecord> {
  return (await api.post<HakpazaRecord>(`/hakpaza/${id}/approve`, {})).data;
}

export async function rejectHakpaza(id: string): Promise<HakpazaRecord> {
  return (await api.post<HakpazaRecord>(`/hakpaza/${id}/reject`, {})).data;
}

export async function listHakpazot(): Promise<HakpazaRecord[]> {
  return (await api.get<HakpazaRecord[]>("/hakpaza")).data;
}

export async function getPendingHakpazaCount(): Promise<number> {
  return (await api.get<{ count: number }>("/hakpaza/pending-count")).data.count;
}
```

- [ ] **Step 2: Create `HakpazaPage.tsx`**

Create `frontend/src/pages/HakpazaPage.tsx`:
```tsx
import { useState } from "react";
import Layout from "../components/Layout";
import SoldierSearchAutocomplete from "../components/SoldierSearchAutocomplete";
import { Assignment, listAssignments } from "../api/assignments";
import { Candidate, createHakpaza, findCandidates } from "../api/hakpaza";
import { formatDate, formatDateRange } from "../utils/formatDate";

type Step = 1 | 2 | 3 | 4 | 5;

export default function HakpazaPage() {
  const [step, setStep] = useState<Step>(1);
  const [pulledSoldierId, setPulledSoldierId] = useState<string | null>(null);
  const [pulledSoldierName, setPulledSoldierName] = useState("");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selectedAssignment, setSelectedAssignment] = useState<Assignment | null>(null);
  const [pullDate, setPullDate] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const today = new Date().toISOString().split("T")[0];

  async function handleSoldierSelect(id: string, name: string) {
    setPulledSoldierId(id);
    setPulledSoldierName(name);
    setLoading(true);
    try {
      const asgns = await listAssignments(id, { date_from: today });
      setAssignments(asgns.filter((a) => a.status === "published"));
      setStep(2);
    } catch {
      setError("שגיאה בטעינת תורנויות החייל");
    } finally {
      setLoading(false);
    }
  }

  async function handleFindCandidates() {
    if (!selectedAssignment) return;
    setLoading(true);
    setError(null);
    try {
      const cands = await findCandidates(selectedAssignment.id, pullDate || selectedAssignment.start_date);
      setCandidates(cands);
      setStep(3);
    } catch {
      setError("שגיאה בחיפוש מחליפים");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    if (!selectedAssignment || !selectedCandidate) return;
    setLoading(true);
    try {
      await createHakpaza(selectedAssignment.id, pullDate || selectedAssignment.start_date, selectedCandidate.soldier_id);
      setDone(true);
      setStep(5);
    } catch {
      setError("שגיאה ביצירת בקשת ההקפצה");
    } finally {
      setLoading(false);
    }
  }

  const DISTANCE_LABEL: Record<number, string> = {
    0: "אותו מדור",
    1: "מדור אחות",
    2: "ענף אחר",
  };

  return (
    <Layout>
      <div className="max-w-2xl mx-auto space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">הקפצה פיקודית</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
        )}

        {/* Step 1: Select soldier */}
        {step >= 1 && (
          <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 1 ? "opacity-60" : ""}`}>
            <h2 className="font-medium text-sm text-gray-500">שלב 1 — בחר חייל להקפיץ</h2>
            <SoldierSearchAutocomplete
              onSelect={(id, name) => { if (step === 1) void handleSoldierSelect(id, name); }}
              placeholder="חפש חייל..."
            />
            {pulledSoldierName && step > 1 && (
              <p className="text-sm font-medium">{pulledSoldierName}</p>
            )}
          </div>
        )}

        {/* Step 2: Select assignment + pull date */}
        {step >= 2 && (
          <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 2 ? "opacity-60" : ""}`}>
            <h2 className="font-medium text-sm text-gray-500">שלב 2 — בחר תורנות ותאריך הקפצה</h2>
            {assignments.length === 0 ? (
              <p className="text-sm text-gray-500">אין תורנויות עתידיות לחייל זה</p>
            ) : (
              <div className="space-y-2">
                {assignments.map((a) => (
                  <label
                    key={a.id}
                    className={`flex items-center gap-3 p-2 border rounded cursor-pointer ${selectedAssignment?.id === a.id ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950" : "border-gray-200 dark:border-gray-700"}`}
                  >
                    <input
                      type="radio"
                      name="assignment"
                      onChange={() => {
                        setSelectedAssignment(a);
                        setPullDate(a.start_date >= today ? a.start_date : today);
                      }}
                    />
                    <span className="text-sm">
                      {formatDateRange(a.start_date, a.end_date)} — {a.duty_type_id.slice(0, 8)}
                    </span>
                  </label>
                ))}
              </div>
            )}

            {selectedAssignment && selectedAssignment.start_date < today && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  תאריך הקפצה (מתי החייל יוחלף):
                </label>
                <input
                  type="date"
                  min={today}
                  max={selectedAssignment.end_date}
                  value={pullDate}
                  onChange={(e) => setPullDate(e.target.value)}
                  className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </div>
            )}

            {step === 2 && (
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={!selectedAssignment || loading}
                onClick={() => void handleFindCandidates()}
              >
                {loading ? "מחפש מחליפים..." : "חפש מחליפים ›"}
              </button>
            )}
          </div>
        )}

        {/* Step 3: Candidates table */}
        {step >= 3 && (
          <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 3 ? "opacity-60" : ""}`}>
            <h2 className="font-medium text-sm text-gray-500">שלב 3 — בחר מחליף ({candidates.length} אפשרויות)</h2>
            {candidates.length === 0 ? (
              <p className="text-sm text-gray-500">לא נמצאו מחליפים כשירים</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b dark:border-gray-700">
                      <th className="text-right pb-1 w-6"></th>
                      <th className="text-right pb-1">שם</th>
                      <th className="text-right pb-1">מדור</th>
                      <th className="text-right pb-1">קרבה</th>
                      <th className="text-right pb-1">ניקוד</th>
                      <th className="text-right pb-1">הקפצות אחרונות</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((c) => (
                      <tr
                        key={c.soldier_id}
                        className={`border-b dark:border-gray-700 cursor-pointer ${selectedCandidate?.soldier_id === c.soldier_id ? "bg-indigo-50 dark:bg-indigo-950" : "hover:bg-gray-50 dark:hover:bg-gray-700"}`}
                        onClick={() => setSelectedCandidate(c)}
                      >
                        <td className="py-1">
                          <input
                            type="radio"
                            name="candidate"
                            checked={selectedCandidate?.soldier_id === c.soldier_id}
                            onChange={() => setSelectedCandidate(c)}
                          />
                        </td>
                        <td className="py-1 font-medium">{c.full_name}</td>
                        <td className="py-1">{c.hierarchy_node_name}</td>
                        <td className="py-1">{DISTANCE_LABEL[c.hierarchy_distance] ?? `${c.hierarchy_distance} רמות`}</td>
                        <td className="py-1">{c.current_score.toFixed(1)}</td>
                        <td className="py-1">{c.recent_forced_callups_decayed.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {step === 3 && selectedCandidate && (
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700"
                onClick={() => setStep(4)}
              >
                המשך עם {selectedCandidate.full_name} ›
              </button>
            )}
          </div>
        )}

        {/* Step 4: Confirmation */}
        {step === 4 && selectedCandidate && selectedAssignment && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <h2 className="font-medium text-sm text-gray-500">שלב 4 — אישור הקפצה</h2>
            <div className="bg-amber-50 dark:bg-amber-950 rounded p-3 text-sm space-y-1">
              <p><span className="text-gray-500">חייל מוקפץ:</span> <strong>{selectedCandidate.full_name}</strong></p>
              <p><span className="text-gray-500">תורנות:</span> {formatDateRange(pullDate || selectedAssignment.start_date, selectedAssignment.end_date)}</p>
              <p><span className="text-gray-500">ימים:</span> {selectedCandidate.days_remaining}</p>
              <p className="text-xs text-gray-500 mt-2">
                הבקשה תישלח לאישור מפקד {selectedCandidate.full_name}. עד אז השיבוץ המקורי נשאר בתוקף.
              </p>
            </div>
            <div className="flex gap-3">
              <button
                className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => setStep(3)}
              >
                חזור
              </button>
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={loading}
                onClick={() => void handleSubmit()}
              >
                {loading ? "שולח..." : "שלח לאישור"}
              </button>
            </div>
          </div>
        )}

        {/* Step 5: Done */}
        {step === 5 && done && (
          <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-lg p-6 text-center space-y-3">
            <p className="text-green-700 dark:text-green-300 font-semibold">בקשת ההקפצה נשלחה</p>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              מפקד {selectedCandidate?.full_name} יקבל התראה לאישור. תישלח הודעה בסיום.
            </p>
            <button
              className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
              onClick={() => {
                setStep(1); setPulledSoldierId(null); setPulledSoldierName("");
                setAssignments([]); setSelectedAssignment(null); setPullDate("");
                setCandidates([]); setSelectedCandidate(null); setDone(false);
              }}
            >
              הקפצה חדשה
            </button>
          </div>
        )}
      </div>
    </Layout>
  );
}
```

- [ ] **Step 3: Add route and nav entry**

In `frontend/src/App.tsx`:
```tsx
import HakpazaPage from "./pages/HakpazaPage";
<Route path="/commander/hakpaza" element={<HakpazaPage />} />
```

In `frontend/src/components/NavSheet.tsx`, inside the commander section:
```tsx
{ label: "הקפצה פיקודית", to: "/commander/hakpaza" }
```

- [ ] **Step 4: Add pending hakpaza count to nav badge**

In `frontend/src/components/UnifiedNav.tsx`, import and add:
```tsx
import { getPendingHakpazaCount } from "../api/hakpaza";
// in the canApprove effect:
const hk = await getPendingHakpazaCount().catch(() => 0);
setPendingCount(c + e + f + enr + hk);
```

- [ ] **Step 5: Run lint**

```bash
cd frontend && pnpm lint
```
Expected: zero errors.

- [ ] **Step 6: Smoke test**

Start dev stack (`.\dev.ps1 -NoBot`):
1. Navigate to מפקד → הקפצה פיקודית.
2. Search for a soldier with active assignments.
3. Select an assignment and click "חפש מחליפים".
4. Verify candidates table renders with correct columns.
5. Pick a candidate and submit → "בקשת ההקפצה נשלחה" screen.
6. Navigate to `/hakpaza` (GET) in the API docs — verify the record exists with `status: "pending"`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/hakpaza.ts frontend/src/pages/HakpazaPage.tsx frontend/src/App.tsx frontend/src/components/NavSheet.tsx frontend/src/components/UnifiedNav.tsx
git commit -m "feat: הקפצה פיקודית page — 5-step wizard with solver-ranked candidates"
```
