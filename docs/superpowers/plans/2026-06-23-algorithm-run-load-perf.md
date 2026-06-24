# Algorithm Run Load Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the two bottlenecks that make `GET /algorithm/jobs/{job_id}` slow for large jobs: an unindexed audit-log full scan and loading megabytes of explanation payloads just to extract 4 scalar values.

**Architecture:** Add `algorithm_job_id` FK + 4 score columns to `duty_assignments`. Populate them during `persist_results`. Replace the audit-log + explanation-payload path in `_proposals_for_job` with a single indexed `WHERE algorithm_job_id = ?` query. Old jobs (no `algorithm_job_id`) fall back to the existing slow path.

**Tech Stack:** PostgreSQL, SQLAlchemy ORM (mapped columns), Alembic migrations, pytest

---

## File Map

| File | Change |
|---|---|
| `backend/alembic/versions/0058_add_job_id_scores_to_duty_assignments.py` | **Create** — migration |
| `backend/app/db/models.py` | **Modify** — 5 new columns on `DutyAssignment` |
| `backend/app/routes/algorithm.py` | **Modify** — fast path in `_proposals_for_job` |
| `backend/app/services/algorithm_bridge.py` | **Modify** — populate columns in `persist_results` |
| `backend/tests/unit/test_algorithm_perf.py` | **Create** — unit tests for fast path and persist_results |

---

### Task 1: Migration

**Files:**
- Create: `backend/alembic/versions/0058_add_job_id_scores_to_duty_assignments.py`

- [ ] **Step 1: Create migration file**

```python
# backend/alembic/versions/0058_add_job_id_scores_to_duty_assignments.py
"""add algorithm_job_id and score columns to duty_assignments

Revision ID: 0058
Revises: 0057
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column(
            "algorithm_job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("algorithm_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("duty_assignments", sa.Column("norm_score_before", sa.Float, nullable=True))
    op.add_column("duty_assignments", sa.Column("norm_score_after", sa.Float, nullable=True))
    op.add_column("duty_assignments", sa.Column("candidate_rank", sa.Integer, nullable=True))
    op.add_column("duty_assignments", sa.Column("candidate_pool_size", sa.Integer, nullable=True))
    op.create_index(
        "idx_duty_assignments_job_id",
        "duty_assignments",
        ["algorithm_job_id"],
        postgresql_where=sa.text("algorithm_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_duty_assignments_job_id", table_name="duty_assignments")
    op.drop_column("duty_assignments", "candidate_pool_size")
    op.drop_column("duty_assignments", "candidate_rank")
    op.drop_column("duty_assignments", "norm_score_after")
    op.drop_column("duty_assignments", "norm_score_before")
    op.drop_column("duty_assignments", "algorithm_job_id")
```

- [ ] **Step 2: Apply migration**

Run from the `backend/` directory (with venv active):
```bash
alembic upgrade head
```

Expected: `Running upgrade 0057 -> 0058, add algorithm_job_id and score columns to duty_assignments`

---

### Task 2: Add columns to the DutyAssignment model

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add 5 mapped columns to `DutyAssignment`**

In `backend/app/db/models.py`, find the `DutyAssignment` class (around line 233). After the `batch_index` column (line 268–270), add:

```python
    algorithm_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("algorithm_jobs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    norm_score_before: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    norm_score_after: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    candidate_rank: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    candidate_pool_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
```

Also add `Float` and `Integer` to the SQLAlchemy imports at the top of `models.py` if not already present. Check the existing imports — `Boolean` and `Integer` are already there; `Float` may not be. The import block looks like:

```python
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,      # add if missing
    ForeignKey,
    Integer,
    Numeric,
    Text,
    text,
)
```

- [ ] **Step 2: Verify the model loads**

```bash
cd backend
python -c "from app.db.models import DutyAssignment; print([c.key for c in DutyAssignment.__table__.columns if 'score' in c.key or 'job' in c.key])"
```

Expected output (order may vary):
```
['algorithm_job_id', 'norm_score_before', 'norm_score_after', 'candidate_rank', 'candidate_pool_size']
```

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0058_add_job_id_scores_to_duty_assignments.py backend/app/db/models.py
git commit -m "feat: add algorithm_job_id and score columns to duty_assignments"
```

---

### Task 3: Fast path in `_proposals_for_job`

**Files:**
- Create: `backend/tests/unit/test_algorithm_perf.py`
- Modify: `backend/app/routes/algorithm.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_algorithm_perf.py`:

```python
from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy import select

from app.db.models import AlgorithmJob, DutyAssignment, DutyLocation, DutyType
from app.routes.algorithm import _proposals_for_job
from tests.helpers import create_node, create_soldier


def _setup_job(session, pn_suffix: str):
    dt = DutyType(name=f"שמירה_{pn_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"שער_{pn_suffix}")
    session.add(dt)
    session.add(loc)
    session.flush()
    node = create_node(session, level="branch", name=f"node_{pn_suffix}")
    dm = create_soldier(
        session,
        personal_number=f"perf_dm_{pn_suffix}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    job = AlgorithmJob(
        planning_start=date(2027, 2, 1),
        planning_end=date(2027, 2, 7),
        shift_ids=[],
        settings_json={},
        mode="shadow",
        created_by=dm.id,
        status="done",
    )
    session.add(job)
    session.flush()
    return dt, loc, dm, job


def test_proposals_fast_path_returns_proposals(admin_session):
    dt, loc, dm, job = _setup_job(admin_session, "fp1")
    soldier = create_soldier(admin_session, personal_number="perf_s_fp1")

    assignment = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 2),
        status="algorithm_draft",
        algorithm_job_id=job.id,
        norm_score_before=0.4,
        norm_score_after=0.6,
        candidate_rank=1,
        candidate_pool_size=5,
    )
    admin_session.add(assignment)
    admin_session.commit()

    proposals = _proposals_for_job(admin_session, job)

    assert len(proposals) == 1
    p = proposals[0]
    assert p.assignment_id == assignment.id
    assert p.soldier_id == soldier.id
    assert p.norm_score_before == pytest.approx(0.4)
    assert p.norm_score_after == pytest.approx(0.6)
    assert p.candidate_rank == 1
    assert p.candidate_pool_size == 5
    assert p.reserve_assignment_id is None


def test_proposals_fast_path_no_audit_log_dependency(admin_session):
    """Fast path must return proposals without any audit_log rows present."""
    dt, loc, dm, job = _setup_job(admin_session, "fp2")
    soldier = create_soldier(admin_session, personal_number="perf_s_fp2")

    # No audit_log rows written for this job
    assignment = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 2),
        status="algorithm_draft",
        algorithm_job_id=job.id,
        norm_score_before=0.1,
        norm_score_after=0.2,
        candidate_rank=3,
        candidate_pool_size=8,
    )
    admin_session.add(assignment)
    admin_session.commit()

    proposals = _proposals_for_job(admin_session, job)
    assert len(proposals) == 1


def test_proposals_pending_job_returns_empty(admin_session):
    _, _, dm, job = _setup_job(admin_session, "fp3")
    job.status = "pending"
    admin_session.commit()

    proposals = _proposals_for_job(admin_session, job)
    assert proposals == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend
pytest tests/unit/test_algorithm_perf.py -v
```

Expected: `FAILED` — either `AttributeError: 'DutyAssignment' has no attribute 'algorithm_job_id'` (if Task 2 not done) or the fast path doesn't exist yet.

- [ ] **Step 3: Implement the fast path in `_proposals_for_job`**

In `backend/app/routes/algorithm.py`, replace the entire `_proposals_for_job` function (lines 221–301) with:

```python
def _proposals_for_job(session: Session, job: AlgorithmJob) -> list[ProposalOut]:
    """Load proposals created for this job."""
    if job.status not in ("done", "published"):
        return []

    # Fast path: new jobs have algorithm_job_id set directly on assignments.
    fast_rows = (
        session.execute(
            select(DutyAssignment).where(DutyAssignment.algorithm_job_id == job.id)
        )
        .scalars()
        .all()
    )

    if fast_rows:
        assignment_ids = {a.id for a in fast_rows}
        reserve_links = (
            session.execute(
                select(DutyReserveLink).where(
                    DutyReserveLink.primary_assignment_id.in_(assignment_ids)
                )
            )
            .scalars()
            .all()
        )
        reserve_map = {lk.primary_assignment_id: lk.reserve_assignment_id for lk in reserve_links}
        return [
            ProposalOut(
                assignment_id=a.id,
                soldier_id=a.soldier_id,
                duty_type_id=a.duty_type_id,
                duty_location_id=a.duty_location_id,
                start_date=a.start_date,
                end_date=a.end_date,
                status=a.status,
                reserve_assignment_id=reserve_map.get(a.id),
                norm_score_before=a.norm_score_before,
                norm_score_after=a.norm_score_after,
                duty_shift_id=a.duty_shift_id,
                candidate_rank=a.candidate_rank,
                candidate_pool_size=a.candidate_pool_size,
                batch_index=a.batch_index,
            )
            for a in fast_rows
        ]

    # Fallback: old jobs without algorithm_job_id — audit-log path.
    from app.db.models import AuditLog

    audit_rows = session.execute(
        select(AuditLog.entity_id).where(
            AuditLog.action == "algorithm.proposal.create",
            AuditLog.context["job_id"].astext == str(job.id),
        )
    ).scalars().all()

    assignment_ids = {eid for eid in audit_rows if eid is not None}
    if not assignment_ids:
        return []

    rows = (
        session.execute(
            select(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids))
        )
        .scalars()
        .all()
    )
    reserve_links = (
        session.execute(
            select(DutyReserveLink).where(
                DutyReserveLink.primary_assignment_id.in_(assignment_ids)
            )
        )
        .scalars()
        .all()
    )
    reserve_map = {lk.primary_assignment_id: lk.reserve_assignment_id for lk in reserve_links}

    explanations = (
        session.execute(
            select(AssignmentExplanation).where(
                AssignmentExplanation.duty_assignment_id.in_(assignment_ids)
            )
        )
        .scalars()
        .all()
    )
    exp_map = {e.duty_assignment_id: e for e in explanations}

    proposals = []
    for a in rows:
        exp = exp_map.get(a.id)
        norm_before = None
        norm_after = None
        candidate_rank = None
        candidate_pool_size = None
        if exp:
            payload = exp.payload
            candidates = payload.get("candidates", [])
            for c in candidates:
                if c["soldier_id"] == str(a.soldier_id) and not c.get("blocked"):
                    norm_before = c.get("pre_norm_score")
                    norm_after = c.get("post_norm_score")
                    break
            candidate_rank, candidate_pool_size = _compute_candidate_rank(
                candidates, str(a.soldier_id), payload=payload
            )
        proposals.append(
            ProposalOut(
                assignment_id=a.id,
                soldier_id=a.soldier_id,
                duty_type_id=a.duty_type_id,
                duty_location_id=a.duty_location_id,
                start_date=a.start_date,
                end_date=a.end_date,
                status=a.status,
                reserve_assignment_id=reserve_map.get(a.id),
                norm_score_before=norm_before,
                norm_score_after=norm_after,
                duty_shift_id=a.duty_shift_id,
                candidate_rank=candidate_rank,
                candidate_pool_size=candidate_pool_size,
                batch_index=a.batch_index,
            )
        )
    return proposals
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
cd backend
pytest tests/unit/test_algorithm_perf.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_algorithm_perf.py backend/app/routes/algorithm.py
git commit -m "feat: fast path in _proposals_for_job using algorithm_job_id FK"
```

---

### Task 4: Populate columns in `persist_results`

**Files:**
- Modify: `backend/tests/unit/test_algorithm_perf.py`
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_algorithm_perf.py`:

```python
import uuid as _uuid
from sqlalchemy import select as _select

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation as AlgoExplanation,
    CandidateInfo,
    DutyBlock,
    ExplanationData,
    SolverResult,
)
from app.services.algorithm_bridge import persist_results


def test_persist_results_sets_job_id_and_scores(admin_session):
    dt = DutyType(name="שמירה_pr1", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="שער_pr1")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    node = create_node(admin_session, level="branch", name="pr_node_1")
    dm = create_soldier(
        admin_session, personal_number="perf_dm_pr1", role="duty_manager", hierarchy_node_id=node.id
    )
    soldier = create_soldier(admin_session, personal_number="perf_s_pr1")

    job = AlgorithmJob(
        planning_start=date(2027, 3, 1),
        planning_end=date(2027, 3, 7),
        shift_ids=[],
        settings_json={},
        mode="shadow",
        created_by=dm.id,
        status="done",
    )
    admin_session.add(job)
    admin_session.commit()

    duty_id = _uuid.uuid4()
    block = DutyBlock(
        id=duty_id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 3, 1),
        end_date=date(2027, 3, 2),
        score_per_day=Decimal("1.00"),
        is_reserve=False,
    )
    result = SolverResult(
        assignments=[Assignment(duty_id=duty_id, soldier_id=soldier.id)],
        status="OPTIMAL",
    )
    other_soldier_id = _uuid.uuid4()
    exp = AlgoExplanation(
        duty_id=duty_id,
        assigned_soldier_id=soldier.id,
        candidates=[
            CandidateInfo(
                soldier_id=other_soldier_id,
                blocked=False,
                pre_effort_score=0.2,
                post_effort_score=0.3,
            ),
            CandidateInfo(
                soldier_id=soldier.id,
                blocked=False,
                pre_effort_score=0.5,
                post_effort_score=0.7,
            ),
        ],
    )
    explanation_data = ExplanationData(per_assignment=[exp])

    persist_results(
        admin_session,
        job=job,
        result=result,
        explanation_data=explanation_data,
        duty_blocks=[block],
        soldier_names={soldier.id: "Test Soldier", other_soldier_id: "Other Soldier"},
        actor_id=dm.id,
    )
    admin_session.commit()

    da = admin_session.execute(
        _select(DutyAssignment).where(DutyAssignment.algorithm_job_id == job.id)
    ).scalar_one()

    assert da.algorithm_job_id == job.id
    assert da.norm_score_before == pytest.approx(0.5)
    assert da.norm_score_after == pytest.approx(0.7)
    # soldier has score 0.5, other has 0.2 → other ranks 1st, soldier ranks 2nd
    assert da.candidate_rank == 2
    assert da.candidate_pool_size == 2


def test_persist_results_reserve_skips_scores(admin_session):
    """Reserve assignments get algorithm_job_id but NOT score columns (no explanation)."""
    dt = DutyType(name="שמירה_pr2", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="שער_pr2")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    node = create_node(admin_session, level="branch", name="pr_node_2")
    dm = create_soldier(
        admin_session, personal_number="perf_dm_pr2", role="duty_manager", hierarchy_node_id=node.id
    )
    soldier = create_soldier(admin_session, personal_number="perf_s_pr2")

    job = AlgorithmJob(
        planning_start=date(2027, 4, 1),
        planning_end=date(2027, 4, 7),
        shift_ids=[],
        settings_json={},
        mode="shadow",
        created_by=dm.id,
        status="done",
    )
    admin_session.add(job)
    admin_session.commit()

    duty_id = _uuid.uuid4()
    block = DutyBlock(
        id=duty_id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 4, 1),
        end_date=date(2027, 4, 2),
        score_per_day=Decimal("1.00"),
        is_reserve=True,
    )
    result = SolverResult(
        assignments=[Assignment(duty_id=duty_id, soldier_id=soldier.id)],
        status="OPTIMAL",
    )
    explanation_data = ExplanationData(per_assignment=[])  # reserves have no explanation

    persist_results(
        admin_session,
        job=job,
        result=result,
        explanation_data=explanation_data,
        duty_blocks=[block],
        soldier_names={soldier.id: "Reserve Soldier"},
        actor_id=dm.id,
    )
    admin_session.commit()

    da = admin_session.execute(
        _select(DutyAssignment).where(DutyAssignment.algorithm_job_id == job.id)
    ).scalar_one()

    assert da.algorithm_job_id == job.id
    assert da.norm_score_before is None
    assert da.candidate_rank is None
```

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd backend
pytest tests/unit/test_algorithm_perf.py::test_persist_results_sets_job_id_and_scores tests/unit/test_algorithm_perf.py::test_persist_results_reserve_skips_scores -v
```

Expected: both `FAILED` — `algorithm_job_id` not set on the assignment.

- [ ] **Step 3: Implement in `persist_results` — Pass 1: set `algorithm_job_id`**

In `backend/app/services/algorithm_bridge.py`, find pass 1 in `persist_results` (around line 596–616). In the `DutyAssignment(...)` constructor call, add `algorithm_job_id=job.id`:

```python
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            start_time=block.start_time,
            end_time=block.end_time,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
            duty_shift_id=shift_id,
            is_reserve=block.is_reserve,
            algorithm_job_id=job.id,   # NEW
        )
```

- [ ] **Step 4: Implement in `persist_results` — Pass 2: set score columns**

In `backend/app/services/algorithm_bridge.py`, find pass 2 (around line 640–655). Replace the existing block:

```python
    # Pass 2: insert AssignmentExplanation rows (FK to duty_assignments now safe)
    for da, duty_id in created:
        block: DutyBlock = duty_map[duty_id]
        if not block.is_reserve:
            exp = explanation_map.get(duty_id)
            if exp is not None:
                payload = _explanation_payload(exp, dm_view=True, soldier_names=soldier_names)
                payload["global_before"] = explanation_data.global_metrics_before
                payload["global_after"] = explanation_data.global_metrics_after
                session.add(AssignmentExplanation(
                    duty_assignment_id=da.id,
                    payload=payload,
                    algorithm_version=explanation_data.algorithm_version,
                    solver_seed=str(explanation_data.solver_seed),
                ))
```

With:

```python
    # Pass 2: insert AssignmentExplanation rows (FK to duty_assignments now safe)
    for da, duty_id in created:
        block: DutyBlock = duty_map[duty_id]
        if not block.is_reserve:
            exp = explanation_map.get(duty_id)
            if exp is not None:
                # Extract scalar fields from the full (pre-truncation) candidate list
                # and store them on the assignment for fast proposal loading.
                assigned_id = exp.assigned_soldier_id
                unblocked = [c for c in exp.candidates if not c.blocked]
                pool_size = len(unblocked)
                unblocked_sorted = sorted(
                    unblocked,
                    key=lambda c: c.pre_effort_score if c.pre_effort_score is not None else float("inf"),
                )
                candidate_rank = next(
                    (i + 1 for i, c in enumerate(unblocked_sorted) if c.soldier_id == assigned_id),
                    None,
                )
                assigned_c = next(
                    (c for c in unblocked if c.soldier_id == assigned_id), None
                )
                da.norm_score_before = assigned_c.pre_effort_score if assigned_c else None
                da.norm_score_after = assigned_c.post_effort_score if assigned_c else None
                da.candidate_rank = candidate_rank
                da.candidate_pool_size = pool_size

                payload = _explanation_payload(exp, dm_view=True, soldier_names=soldier_names)
                payload["global_before"] = explanation_data.global_metrics_before
                payload["global_after"] = explanation_data.global_metrics_after
                session.add(AssignmentExplanation(
                    duty_assignment_id=da.id,
                    payload=payload,
                    algorithm_version=explanation_data.algorithm_version,
                    solver_seed=str(explanation_data.solver_seed),
                ))
```

- [ ] **Step 5: Run all perf tests**

```bash
cd backend
pytest tests/unit/test_algorithm_perf.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/tests/unit/test_algorithm_perf.py backend/app/services/algorithm_bridge.py
git commit -m "feat: populate algorithm_job_id and score columns in persist_results"
```

---

### Task 5: Verify existing test suite still passes

**Files:** none modified

- [ ] **Step 1: Run the full algorithm and bridge test suite**

```bash
cd backend
pytest -m "algorithm" -q
```

Expected: all pass (no regressions in algorithm area).

- [ ] **Step 2: Run the broader unit test suite**

```bash
cd backend
pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 3: Run integration tests**

```bash
cd backend
pytest tests/integration/ -q
```

Expected: all pass. The `test_notification_created_when_job_completes` test exercises the full end-to-end path including `persist_results` and `GET /api/algorithm/jobs/{job_id}`.

- [ ] **Step 4: Final commit if any fixups were needed**

```bash
git add -p   # stage only the fixup changes
git commit -m "fix: <describe what broke>"
```
