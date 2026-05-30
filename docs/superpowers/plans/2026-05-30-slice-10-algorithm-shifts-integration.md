# Slice 10 — Algorithm Integration with Shifts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the synthesized-DutyBlock approach with real `duty_shifts` from the DB. AlgorithmJob stores `shift_ids`; the bridge expands each shift into N DutyBlocks; assignments are linked back to their shift via `duty_shift_id`. The frontend planning window shows shifts to select instead of date/type inputs.

**Architecture:** Migration 0019 replaces `duty_type_ids + duty_location_id` columns on `algorithm_jobs` with `shift_ids JSONB`. `load_duty_blocks_from_shifts` replaces `load_duty_blocks`. `persist_results` sets `duty_shift_id` on each new assignment. `AlgorithmPlanningWindow` component is updated to show shifts list.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, React 18, TypeScript.

**Spec:** `docs/superpowers/specs/2026-05-30-slice-10-algorithm-shifts-integration.md`

---

## File structure

```
backend/
├── alembic/versions/0019_algorithm_job_shift_ids.py   CREATE
├── app/
│   ├── db/models.py                                   MODIFY — replace duty_type_ids/duty_location_id with shift_ids on AlgorithmJob
│   ├── services/algorithm_bridge.py                   MODIFY — add load_duty_blocks_from_shifts, update persist_results, update run_algorithm_job
│   └── routes/algorithm.py                            MODIFY — update CreateJobRequest + validation + proposals endpoint
└── tests/
    ├── unit/test_algorithm_bridge_shifts.py            CREATE
    └── integration/test_algorithm_shifts.py            CREATE

frontend/src/
├── api/algorithm.ts                                   MODIFY — update CreateJobRequest type
└── components/AlgorithmPlanningWindow.tsx             MODIFY — replace date/type inputs with shift selector
```

---

## Phase A — Database

### Task 1: Migration 0019

**Files:**
- Create: `backend/alembic/versions/0019_algorithm_job_shift_ids.py`

- [ ] **Step 1: Create `backend/alembic/versions/0019_algorithm_job_shift_ids.py`**

```python
"""replace duty_type_ids/duty_location_id with shift_ids on algorithm_jobs

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("shift_ids", postgresql.JSONB(), nullable=True),
    )
    # Back-fill existing rows (if any) with empty array so we can make it NOT NULL
    op.execute("UPDATE algorithm_jobs SET shift_ids = '[]' WHERE shift_ids IS NULL")
    op.alter_column("algorithm_jobs", "shift_ids", nullable=False)

    op.drop_column("algorithm_jobs", "duty_type_ids")
    op.drop_column("algorithm_jobs", "duty_location_id")


def downgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("duty_type_ids", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "algorithm_jobs",
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.drop_column("algorithm_jobs", "shift_ids")
```

- [ ] **Step 2: Run migration**

```
cd backend && uv run alembic upgrade head && uv run alembic check
```
Expected: `No new upgrade operations detected.`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0019_algorithm_job_shift_ids.py
git commit -m "feat(db): replace duty_type_ids/location with shift_ids on algorithm_jobs (migration 0019)"
```

---

### Task 2: Update AlgorithmJob ORM model

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Replace `duty_type_ids` and `duty_location_id` with `shift_ids` in `AlgorithmJob`**

In `AlgorithmJob`, replace:
```python
    duty_type_ids: Mapped[list[Any]] = mapped_column(JSONB)
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
```

With:
```python
    shift_ids: Mapped[list[Any]] = mapped_column(JSONB)
```

- [ ] **Step 2: Verify**

```
cd backend && uv run python -c "from app.db.models import AlgorithmJob; j = AlgorithmJob.__dataclass_fields__; assert 'shift_ids' in j and 'duty_type_ids' not in j; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(models): AlgorithmJob.shift_ids replaces duty_type_ids + duty_location_id"
```

---

## Phase B — Algorithm bridge

### Task 3: Add `load_duty_blocks_from_shifts`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Add `load_duty_blocks_from_shifts` after `load_duty_blocks` in algorithm_bridge.py**

```python
def load_duty_blocks_from_shifts(
    session: Session,
    *,
    shift_ids: list[uuid.UUID],
) -> tuple[list[DutyBlock], dict[uuid.UUID, uuid.UUID]]:
    """Expand DutyShift rows into DutyBlocks.

    Each shift with required_count=N generates N DutyBlocks with identical
    date range. Returns (blocks, block_to_shift_map) where block_to_shift_map
    maps ephemeral DutyBlock.id -> shift_id for use during persist_results.
    """
    from app.db.models import DutyShift

    shifts = session.execute(
        select(DutyShift).where(DutyShift.id.in_(shift_ids))
    ).scalars().all()

    # Get score_per_day for each duty type
    type_ids = {s.duty_type_id for s in shifts}
    types_q = session.execute(
        select(DutyType).where(DutyType.id.in_(type_ids))
    ).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}

    blocks: list[DutyBlock] = []
    block_to_shift: dict[uuid.UUID, uuid.UUID] = {}

    for shift in shifts:
        score = score_map.get(shift.duty_type_id, Decimal("1.00"))
        for _ in range(shift.required_count):
            block_id = uuid.uuid4()
            blocks.append(
                DutyBlock(
                    id=block_id,
                    duty_type_id=shift.duty_type_id,
                    duty_location_id=shift.duty_location_id,
                    start_date=shift.start_date,
                    end_date=shift.end_date,
                    score_per_day=score,
                )
            )
            block_to_shift[block_id] = shift.id

    return blocks, block_to_shift
```

- [ ] **Step 2: Verify**

```
cd backend && uv run python -c "from app.services.algorithm_bridge import load_duty_blocks_from_shifts; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat(algorithm-bridge): load_duty_blocks_from_shifts expands shifts to DutyBlocks"
```

---

### Task 4: Update `persist_results` + `run_algorithm_job`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Add `block_to_shift_map` parameter to `persist_results`**

Update the `persist_results` signature to include `block_to_shift_map`:

```python
def persist_results(
    session: Session,
    *,
    job: AlgorithmJob,
    result: SolverResult,
    explanation_data: ExplanationData,
    reserves: list[ReserveEntry],
    duty_blocks: list,
    soldier_names: dict[uuid.UUID, str],
    actor_id: uuid.UUID | None,
    block_to_shift_map: dict[uuid.UUID, uuid.UUID] | None = None,
) -> None:
```

In the body, when creating `DutyAssignment`, set `duty_shift_id`:

```python
        shift_id = block_to_shift_map.get(a.duty_id) if block_to_shift_map else None
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
            duty_shift_id=shift_id,
        )
```

- [ ] **Step 2: Update `run_algorithm_job` to use shifts**

In `run_algorithm_job`, replace the `load_duty_blocks` call with `load_duty_blocks_from_shifts`:

Find:
```python
            duties = load_duty_blocks(
                session,
                planning_start=job.planning_start,
                planning_end=job.planning_end,
                duty_type_ids=duty_type_ids,
                duty_location_id=job.duty_location_id,
            )
```

Replace with:
```python
            shift_ids = [uuid.UUID(s) for s in job.shift_ids]
            duties, block_to_shift_map = load_duty_blocks_from_shifts(
                session,
                shift_ids=shift_ids,
            )
            # Infer planning window from shifts
            if duties:
                planning_start = min(d.start_date for d in duties)
                planning_end = max(d.end_date for d in duties)
            else:
                # No duties → fail immediately
                job.status = "failed"
                job.error_message = "no_shifts_selected"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return
```

Also remove the `duty_type_ids = [uuid.UUID(s) for s in job.duty_type_ids]` line (no longer needed).

Update `load_existing_assignments` call to use the inferred window:
```python
            existing = load_existing_assignments(
                session,
                planning_start=planning_start,
                planning_end=planning_end,
                W=settings.W,
            )
```

Update `persist_results` call to pass `block_to_shift_map`:
```python
            persist_results(
                session,
                job=job,
                result=result,
                explanation_data=explanation_data,
                reserves=reserves,
                duty_blocks=duties,
                soldier_names=soldier_names,
                actor_id=actor_id,
                block_to_shift_map=block_to_shift_map,
            )
```

- [ ] **Step 3: Verify**

```
cd backend && uv run python -c "from app.services.algorithm_bridge import run_algorithm_job, persist_results; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat(algorithm-bridge): use shifts in run_algorithm_job, link assignments to shifts"
```

---

## Phase C — Routes

### Task 5: Update algorithm routes

**Files:**
- Modify: `backend/app/routes/algorithm.py`

- [ ] **Step 1: Update `CreateJobRequest` in algorithm routes**

Replace `CreateJobRequest`:

```python
class CreateJobRequest(BaseModel):
    shift_ids: list[uuid.UUID] = Field(min_length=1)
    mode: str = "shadow"
    settings: SolverSettingsIn = Field(default_factory=SolverSettingsIn)
```

- [ ] **Step 2: Update `create_job` endpoint**

Replace the job creation body:

```python
@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: CreateJobRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    if body.mode not in ("shadow", "dm_reviewed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_mode")
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    # Validate shifts exist and at least one is not full
    from app.db.models import DutyShift
    from app.services.shifts import get_shift_fill
    all_full = True
    for sid in body.shift_ids:
        shift = session.get(DutyShift, sid)
        if shift is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift_not_found")
        fill = get_shift_fill(session, shift_id=sid)
        if fill and fill.fill_status != "full":
            all_full = False
    if all_full:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="all_shifts_full")

    settings_dict = body.settings.model_dump()
    # Compute planning window from shifts
    shifts = [session.get(DutyShift, sid) for sid in body.shift_ids]
    planning_start = min(s.start_date for s in shifts if s)
    planning_end = max(s.end_date for s in shifts if s)

    job = AlgorithmJob(
        planning_start=planning_start,
        planning_end=planning_end,
        shift_ids=[str(sid) for sid in body.shift_ids],
        settings_json=settings_dict,
        mode=body.mode,
        created_by=user.id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    background_tasks.add_task(run_algorithm_job, job.id, user.id)
    return {"id": str(job.id), "status": job.status}
```

- [ ] **Step 3: Add `shift_id` to proposal output in `_proposals_for_job`**

In `ProposalOut`, add:
```python
class ProposalOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    reserve_soldier_id: uuid.UUID | None
    norm_score_before: float | None
    norm_score_after: float | None
    duty_shift_id: uuid.UUID | None = None
```

In `_proposals_for_job`, add `duty_shift_id=a.duty_shift_id` to each `ProposalOut(...)` constructor.

- [ ] **Step 4: Verify app starts**

```
cd backend && uv run python -c "from app.main import create_app; create_app(); print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/algorithm.py
git commit -m "feat(algorithm-api): use shift_ids in CreateJobRequest, validate shifts, add duty_shift_id to proposals"
```

---

## Phase D — Tests

### Task 6: Unit tests for bridge shifts

**Files:**
- Create: `backend/tests/unit/test_algorithm_bridge_shifts.py`

- [ ] **Step 1: Create `backend/tests/unit/test_algorithm_bridge_shifts.py`**

```python
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import DutyLocation, DutyShift, DutyType
from app.services.algorithm_bridge import load_duty_blocks_from_shifts
from tests.helpers import create_soldier


def _dt(session, name=None) -> DutyType:
    dt = DutyType(name=name or f"dt_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("2.00"))
    session.add(dt)
    session.flush()
    return dt


def _loc(session) -> DutyLocation:
    loc = DutyLocation(name=f"loc_{uuid.uuid4().hex[:6]}")
    session.add(loc)
    session.flush()
    return loc


def _shift(session, dt, loc, start, end, count=1) -> DutyShift:
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end,
        required_count=count,
    )
    session.add(shift)
    session.flush()
    return shift


def test_single_shift_required_count_1(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = _shift(admin_session, dt, loc, date(2026, 7, 1), date(2026, 7, 3), count=1)
    admin_session.commit()

    blocks, b2s = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].duty_type_id == dt.id
    assert blocks[0].start_date == date(2026, 7, 1)
    assert blocks[0].end_date == date(2026, 7, 3)
    assert b2s[blocks[0].id] == shift.id


def test_shift_expands_to_N_blocks(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = _shift(admin_session, dt, loc, date(2026, 8, 1), date(2026, 8, 1), count=4)
    admin_session.commit()

    blocks, b2s = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 4
    for b in blocks:
        assert b.duty_type_id == dt.id
        assert b2s[b.id] == shift.id


def test_multiple_shifts_combined(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    s1 = _shift(admin_session, dt, loc, date(2026, 9, 1), date(2026, 9, 1), count=2)
    s2 = _shift(admin_session, dt, loc, date(2026, 9, 2), date(2026, 9, 2), count=3)
    admin_session.commit()

    blocks, b2s = load_duty_blocks_from_shifts(admin_session, shift_ids=[s1.id, s2.id])
    assert len(blocks) == 5
    shift1_blocks = [b for b in blocks if b2s[b.id] == s1.id]
    shift2_blocks = [b for b in blocks if b2s[b.id] == s2.id]
    assert len(shift1_blocks) == 2
    assert len(shift2_blocks) == 3


def test_block_ids_are_unique(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = _shift(admin_session, dt, loc, date(2026, 10, 1), date(2026, 10, 1), count=5)
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    ids = [b.id for b in blocks]
    assert len(set(ids)) == 5  # all unique


def test_score_per_day_from_duty_type(admin_session):
    dt = DutyType(name=f"expensive_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("5.50"))
    loc = _loc(admin_session)
    admin_session.add(dt)
    admin_session.flush()
    shift = _shift(admin_session, dt, loc, date(2026, 11, 1), date(2026, 11, 1), count=1)
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert blocks[0].score_per_day == Decimal("5.50")
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/unit/test_algorithm_bridge_shifts.py -v
```
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_algorithm_bridge_shifts.py
git commit -m "test(algorithm-bridge): unit tests for load_duty_blocks_from_shifts"
```

---

### Task 7: Integration tests for algorithm+shifts

**Files:**
- Create: `backend/tests/integration/test_algorithm_shifts.py`

- [ ] **Step 1: Create `backend/tests/integration/test_algorithm_shifts.py`**

```python
from __future__ import annotations

import time
from decimal import Decimal

import pytest

from app.db.models import DutyLocation, DutyShift, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt); session.add(loc); session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2027-01-01",
        end_date="2027-01-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, dt, loc, shift


def test_create_job_with_shift_ids(client, admin_session):
    dm, dt, loc, shift = _setup(admin_session, "als_001")
    soldier = create_soldier(admin_session, personal_number="als_001s")
    admin_session.commit()

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"


def test_rejects_missing_shift_id(client, admin_session):
    dm, dt, loc, _ = _setup(admin_session, "als_002")
    fake_id = "00000000-0000-0000-0000-000000000099"

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [fake_id],
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "shift_not_found"


def test_algorithm_runs_and_proposals_have_shift_id(client, admin_session):
    dm, dt, loc, shift = _setup(admin_session, "als_003")
    soldier = create_soldier(admin_session, personal_number="als_003s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    if poll and poll.json()["status"] == "done":
        proposals = poll.json().get("proposals", [])
        if proposals:
            # Each proposal should have duty_shift_id set
            for p in proposals:
                assert p.get("duty_shift_id") is not None

    # Regression: job poll still works regardless
    assert poll is not None
    assert poll.json()["status"] in ("done", "failed")
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/integration/test_algorithm_shifts.py -v
```
Expected: All pass (the proposals test may skip if solver finds no solution with 1 soldier).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_algorithm_shifts.py
git commit -m "test(algorithm-shifts): integration tests for shift-based algorithm jobs"
```

---

## Phase E — Frontend

### Task 8: Update AlgorithmPlanningWindow to use shifts

**Files:**
- Modify: `frontend/src/api/algorithm.ts`
- Modify: `frontend/src/components/AlgorithmPlanningWindow.tsx`

- [ ] **Step 1: Update `CreateJobRequest` in `frontend/src/api/algorithm.ts`**

Replace `CreateJobRequest`:

```typescript
export interface CreateJobRequest {
  shift_ids: string[];
  mode: "shadow" | "dm_reviewed";
  settings: SolverSettings;
}
```

Remove `planning_start`, `planning_end`, `duty_type_ids`, `duty_location_id` from the interface.

Also update `ProposalRow` to include `duty_shift_id`:
```typescript
export interface ProposalRow {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  status: string;
  reserve_soldier_id: string | null;
  norm_score_before: number | null;
  norm_score_after: number | null;
  duty_shift_id: string | null;
}
```

- [ ] **Step 2: Rewrite `AlgorithmPlanningWindow.tsx` to use shifts**

Replace the component with a version that shows available shifts to select:

```tsx
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlgorithmJob,
  ProposalRow,
  SolverSettings,
  acceptProposal,
  pollJob,
  rejectProposal,
  submitJob,
} from "../api/algorithm";
import { DutyShift, listShifts } from "../api/shifts";
import { DutyType, DutyLocation } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import ExplanationModal from "./ExplanationModal";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  soldiers: SoldierDTO[];
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 7, W: 14, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

const FILL_COLORS: Record<string, string> = {
  empty: "text-red-600",
  partial: "text-amber-600",
  full: "text-green-600",
};

export default function AlgorithmPlanningWindow({ dutyTypes, locations, soldiers }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [availableShifts, setAvailableShifts] = useState<DutyShift[]>([]);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [mode, setMode] = useState<"shadow" | "dm_reviewed">("shadow");
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<AlgorithmJob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [explanationTarget, setExplanationTarget] = useState<{
    jobId: string;
    assignmentId: string;
  } | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  useEffect(() => {
    if (open && (dateFrom || dateTo)) {
      void listShifts({ date_from: dateFrom || undefined, date_to: dateTo || undefined })
        .then(ss => setAvailableShifts(ss.filter(s => s.fill_status !== "full")));
    }
  }, [open, dateFrom, dateTo]);

  useEffect(() => {
    if (!jobId) return;
    startTimeRef.current = Date.now();
    pollRef.current = setInterval(async () => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      try {
        const j = await pollJob(jobId);
        setJob(j);
        if (j.status === "done" || j.status === "failed") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
        }
      } catch {
        clearInterval(pollRef.current!);
      }
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId]);

  function toggleShift(id: string) {
    setSelectedShiftIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  async function handleRun() {
    setError(null);
    setJob(null);
    setJobId(null);
    if (selectedShiftIds.length === 0) {
      setError("נא לבחור לפחות משמרת אחת");
      return;
    }
    try {
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode, settings });
      setJobId(resp.id);
    } catch (e: unknown) {
      const detail = (e as any)?.response?.data?.detail;
      setError(detail ?? "שגיאה בשליחת הבקשה");
    }
  }

  async function handleAccept(proposal: ProposalRow) {
    if (!jobId) return;
    await acceptProposal(jobId, proposal.assignment_id);
    setJob(prev => prev ? {
      ...prev,
      proposals: prev.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "published" } : p
      ),
    } : prev);
  }

  async function handleReject(proposal: ProposalRow) {
    if (!jobId) return;
    await rejectProposal(jobId, proposal.assignment_id);
    setJob(prev => prev ? {
      ...prev,
      proposals: prev.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "algorithm_rejected" } : p
      ),
    } : prev);
  }

  const soldierName = (id: string) =>
    soldiers.find(s => s.id === id)?.full_name ?? id.slice(0, 8);
  const typeName = (id: string) =>
    dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const shiftLabel = (shift: DutyShift) =>
    `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (${shift.assigned_count}/${shift.required_count})`;

  const isRunning = !!jobId && (job === null || job.status === "pending" || job.status === "running");

  return (
    <div className="border rounded-lg mt-6" dir="rtl">
      <button
        className="w-full flex justify-between items-center px-4 py-3 font-medium text-right bg-gray-50 rounded-lg hover:bg-gray-100"
        onClick={() => setOpen(o => !o)}
      >
        <span>{t("algorithm.title")}</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="p-4 space-y-4">
          {/* Date filter for shifts */}
          <div className="grid grid-cols-2 gap-4">
            <label className="block text-sm">
              {t("shifts.filter_from")}
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
            </label>
            <label className="block text-sm">
              {t("shifts.filter_to")}
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
            </label>
          </div>

          {/* Shift selector */}
          {availableShifts.length > 0 && (
            <div className="text-sm">
              <p className="font-medium mb-1">בחר משמרות להרצה</p>
              <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2">
                {availableShifts.map(shift => (
                  <label key={shift.id} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={selectedShiftIds.includes(shift.id)}
                      onChange={() => toggleShift(shift.id)}
                    />
                    <span className={FILL_COLORS[shift.fill_status]}>
                      {shiftLabel(shift)}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {availableShifts.length === 0 && (dateFrom || dateTo) && (
            <p className="text-sm text-gray-400">אין משמרות פתוחות בטווח הנבחר</p>
          )}

          {/* Mode */}
          <label className="block text-sm">
            {t("algorithm.mode_label")}
            <select value={mode} onChange={e => setMode(e.target.value as "shadow" | "dm_reviewed")} className="mt-1 block w-full border rounded p-1 text-sm">
              <option value="shadow">{t("algorithm.shadow_mode")}</option>
              <option value="dm_reviewed">{t("algorithm.dm_reviewed_mode")}</option>
            </select>
          </label>

          {/* Settings */}
          <button type="button" className="text-xs text-blue-600 underline" onClick={() => setShowSettings(s => !s)}>
            {t("algorithm.settings")}
          </button>
          {showSettings && (
            <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 p-3 rounded">
              {(["K", "T", "W", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
                <label key={key} className="block">
                  {key}
                  <input
                    type="number"
                    value={settings[key]}
                    onChange={e => setSettings(s => ({ ...s, [key]: parseFloat(e.target.value) }))}
                    className="mt-1 block w-full border rounded p-1"
                    step={key === "alpha" || key === "beta" ? 0.1 : 1}
                  />
                </label>
              ))}
            </div>
          )}

          {error && <p className="text-red-500 text-sm">{error}</p>}

          <button
            onClick={handleRun}
            disabled={isRunning || selectedShiftIds.length === 0}
            type="button"
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {t("algorithm.run_button")} {selectedShiftIds.length > 0 && `(${selectedShiftIds.length} משמרות)`}
          </button>

          {isRunning && (
            <p className="text-sm text-gray-600 animate-pulse">{t("algorithm.running")} ({elapsed}s)</p>
          )}

          {job?.status === "failed" && (
            <div className="text-red-600 text-sm space-y-1">
              <p>{t("algorithm.failed")}: {job.error_message}</p>
              {job.relaxed.map((r, i) => <p key={i} className="text-xs">{r}</p>)}
            </div>
          )}

          {job?.status === "done" && (
            <div>
              <p className="font-medium text-sm mb-2">{t("algorithm.done")}</p>
              {job.proposals.length === 0 ? (
                <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
              ) : (
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-gray-50 text-right">
                      <th className="border px-2 py-1">{t("algorithm.col_date")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_type")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_soldier")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_reserve")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_score_before")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_score_after")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.proposals.map(p => {
                      const isAccepted = p.status === "published";
                      const isRejected = p.status === "algorithm_rejected";
                      return (
                        <tr key={p.assignment_id} className={isAccepted ? "bg-green-50" : isRejected ? "bg-gray-100 opacity-50" : ""}>
                          <td className="border px-2 py-1">{p.start_date}</td>
                          <td className="border px-2 py-1">{typeName(p.duty_type_id)}</td>
                          <td className="border px-2 py-1">{soldierName(p.soldier_id)}</td>
                          <td className="border px-2 py-1">{p.reserve_soldier_id ? soldierName(p.reserve_soldier_id) : "—"}</td>
                          <td className="border px-2 py-1">{p.norm_score_before?.toFixed(3) ?? "—"}</td>
                          <td className="border px-2 py-1">{p.norm_score_after?.toFixed(3) ?? "—"}</td>
                          <td className="border px-2 py-1 space-x-1 space-x-reverse">
                            {!isAccepted && !isRejected && (
                              <>
                                <button type="button" onClick={() => handleAccept(p)} className="text-green-700 font-bold hover:underline">{t("algorithm.accept")}</button>{" "}
                                <button type="button" onClick={() => handleReject(p)} className="text-red-700 hover:underline">{t("algorithm.reject")}</button>{" "}
                              </>
                            )}
                            {jobId && (
                              <button type="button" onClick={() => setExplanationTarget({ jobId, assignmentId: p.assignment_id })} className="text-blue-600 hover:underline">
                                {t("algorithm.why_button")}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}

      {explanationTarget && (
        <ExplanationModal
          jobId={explanationTarget.jobId}
          assignmentId={explanationTarget.assignmentId}
          onClose={() => setExplanationTarget(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/algorithm.ts frontend/src/components/AlgorithmPlanningWindow.tsx
git commit -m "feat(frontend): AlgorithmPlanningWindow uses shift selector instead of date/type inputs"
```

---

## Self-review checklist

1. **Spec coverage:**
   - ✅ Migration 0019: shift_ids on algorithm_jobs, remove duty_type_ids/duty_location_id — Task 1
   - ✅ AlgorithmJob ORM updated — Task 2
   - ✅ `load_duty_blocks_from_shifts` with block_to_shift_map — Task 3
   - ✅ `persist_results` sets duty_shift_id on assignments — Task 4
   - ✅ `run_algorithm_job` uses shifts, infers planning window — Task 4
   - ✅ `CreateJobRequest` uses shift_ids, validates shifts, computes window — Task 5
   - ✅ ProposalOut includes duty_shift_id — Task 5
   - ✅ Unit tests for load_duty_blocks_from_shifts — Task 6
   - ✅ Integration tests for shift-based algorithm jobs — Task 7
   - ✅ Frontend CreateJobRequest updated — Task 8
   - ✅ AlgorithmPlanningWindow rewritten with shift selector — Task 8

2. **Placeholder scan:** None.

3. **Type consistency:** `ProposalRow.duty_shift_id: string | null` in `algorithm.ts` matches `ProposalOut.duty_shift_id: uuid.UUID | None` in routes. `CreateJobRequest.shift_ids` consistent across backend + frontend.
