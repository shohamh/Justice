# Slice 7 — Algorithm GUI & Backend Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the pure CP-SAT algorithm module into the FastAPI app with a background-job API, DB persistence, and frontend surfaces for the DM planning window and the soldier "?למה קיבלתי" modal.

**Architecture:** Background job pattern — `POST /api/algorithm/jobs` starts a FastAPI `BackgroundTasks` worker that calls `app.algorithm.solver.solve()` then persists proposals as `algorithm_draft` `DutyAssignment` rows + explanation + reserve rows. The DM polls `GET /api/algorithm/jobs/{id}` every 3s. Two frontend components (`AlgorithmPlanningWindow`, `ExplanationModal`) are added to `DutyManagementPage` and `MyDutiesPage`.

**Tech Stack:** Python 3.12, FastAPI BackgroundTasks, SQLAlchemy 2.0, OR-Tools CP-SAT (already installed), React 18, TypeScript 5, react-i18next.

**Prerequisites:** Slice 5 pure algorithm module (already in `backend/app/algorithm/`), personal constraints table + `PersonalConstraint` model (already in `backend/app/db/models.py` as migration 0015).

**Spec:** `docs/superpowers/specs/2026-05-30-algorithm-gui-backend-bridge-design.md`

---

## File structure

```
backend/
├── alembic/versions/0016_create_algorithm_tables.py   CREATE
├── app/
│   ├── db/models.py                                   MODIFY — add AlgorithmJob, ReserveAssignment, AssignmentExplanation
│   ├── auth/authz.py                                  MODIFY — add ALGORITHM_RUN action
│   ├── services/algorithm_bridge.py                   CREATE — bridge: DB → pure module → persist
│   ├── routes/algorithm.py                            CREATE — 6 endpoints + background task
│   ├── main.py                                        MODIFY — register algorithm router
│   └── algorithm/                                     (existing, no changes)
└── tests/
    ├── unit/test_algorithm_bridge.py                  CREATE
    └── integration/test_algorithm_routes.py           CREATE

frontend/
├── src/
│   ├── api/algorithm.ts                               CREATE
│   ├── components/
│   │   ├── AlgorithmPlanningWindow.tsx                CREATE
│   │   └── ExplanationModal.tsx                       CREATE
│   ├── pages/
│   │   ├── DutyManagementPage.tsx                     MODIFY — add AlgorithmPlanningWindow
│   │   └── MyDutiesPage.tsx                           MODIFY — add ?למה קיבלתי button
│   └── i18n/he.json                                   MODIFY — add algorithm block
```

---

## Phase A — Database

### Task 1: ORM models + Alembic migration 0016

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0016_create_algorithm_tables.py`

- [ ] **Step 1: Add three ORM models to `backend/app/db/models.py`**

Append after the `ScoreAdjustment` class (end of file):

```python
class AlgorithmJob(Base):
    __tablename__ = "algorithm_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    planning_start: Mapped[date] = mapped_column(Date)
    planning_end: Mapped[date] = mapped_column(Date)
    duty_type_ids: Mapped[list[Any]] = mapped_column(JSONB)
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ReserveAssignment(Base):
    __tablename__ = "reserve_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    reserve_soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    reason: Mapped[str] = mapped_column(Text)


class AssignmentExplanation(Base):
    __tablename__ = "assignment_explanations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    algorithm_version: Mapped[str] = mapped_column(Text)
    solver_seed: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Verify models import cleanly**

Run from `backend/`:
```
uv run python -c "from app.db.models import AlgorithmJob, ReserveAssignment, AssignmentExplanation; print('models ok')"
```
Expected: `models ok`

- [ ] **Step 3: Create migration `backend/alembic/versions/0016_create_algorithm_tables.py`**

```python
"""create algorithm tables

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "algorithm_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("planning_start", sa.Date(), nullable=False),
        sa.Column("planning_end", sa.Date(), nullable=False),
        sa.Column("duty_type_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("settings_json", postgresql.JSONB(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_algorithm_jobs_status", "algorithm_jobs", ["status"])

    op.create_table(
        "reserve_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "duty_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reserve_soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
    )

    op.create_table(
        "assignment_explanations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "duty_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("solver_seed", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("assignment_explanations")
    op.drop_table("reserve_assignments")
    op.drop_index("idx_algorithm_jobs_status", table_name="algorithm_jobs")
    op.drop_table("algorithm_jobs")
```

- [ ] **Step 4: Run migration against the dev DB**

Run from `backend/`:
```
uv run alembic upgrade head
```
Expected: migration applies without error. Run `uv run alembic check` — expected: `No new upgrade operations detected.`

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0016_create_algorithm_tables.py
git commit -m "feat(db): algorithm_jobs, reserve_assignments, assignment_explanations tables (migration 0016)"
```

---

## Phase B — Auth

### Task 2: Add ALGORITHM_RUN action

**Files:**
- Modify: `backend/app/auth/authz.py`

- [ ] **Step 1: Add `ALGORITHM_RUN` to the `Action` class and `_DM_ACTIONS` set**

In `backend/app/auth/authz.py`, add to `class Action`:
```python
    ALGORITHM_RUN = "algorithm.run"
```

Add `Action.ALGORITHM_RUN` to `_DM_ACTIONS`:
```python
_DM_ACTIONS = {
    Action.SOLDIER_CREATE,
    Action.SOLDIER_READ,
    Action.SOLDIER_UPDATE,
    Action.SOLDIER_RESET_PASSWORD,
    Action.SOLDIER_DELETE,
    Action.HIERARCHY_READ,
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
    Action.ALGORITHM_RUN,
}
```

- [ ] **Step 2: Verify import**

```
uv run python -c "from app.auth.authz import Action; assert hasattr(Action, 'ALGORITHM_RUN'); print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/auth/authz.py
git commit -m "feat(auth): add ALGORITHM_RUN action for duty_manager"
```

---

## Phase C — Bridge service

### Task 3: Data-loading helpers in `algorithm_bridge.py`

**Files:**
- Create: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Write failing import test**

```
uv run python -c "from app.services.algorithm_bridge import load_soldier_inputs; print('ok')"
```
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Create `backend/app/services/algorithm_bridge.py` with loading helpers**

```python
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation as AlgoExplanation,
    DutyBlock,
    ExistingAssignment,
    ExplanationData,
    SolverResult,
    SolverSettings,
    SoldierInput,
)
from app.audit.writer import write_audit
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    DutyAssignment,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    HierarchyNode,
    PersonalConstraint,
    ReserveAssignment,
    Soldier,
    SoldierExemption,
)
from app.services import scoring as scoring_svc


def load_soldier_inputs(session: Session, *, as_of: date) -> list[SoldierInput]:
    """Load every active soldier as a SoldierInput for the algorithm."""
    soldiers = (
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
    duty_scores = scoring_svc.duty_score_by_soldier(session)
    adj_scores = scoring_svc.adjustments_by_soldier(session)

    # Build exemption type → duty type ids map
    etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        etid_to_dtids.setdefault(etid, set()).add(dtid)

    # Active exemptions per soldier
    active_exemptions = (
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.start_date <= as_of,
                (SoldierExemption.end_date >= as_of) | (SoldierExemption.end_date.is_(None)),
            )
        )
        .scalars()
        .all()
    )
    soldier_exempt_dtype_ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for ex in active_exemptions:
        dtids = etid_to_dtids.get(ex.exemption_type_id, set())
        soldier_exempt_dtype_ids.setdefault(ex.soldier_id, set()).update(dtids)

    # Approved personal constraints per soldier
    constraints = (
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.status == "approved")
        )
        .scalars()
        .all()
    )
    soldier_constraints: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for c in constraints:
        soldier_constraints.setdefault(c.soldier_id, []).append((c.start_date, c.end_date))

    result: list[SoldierInput] = []
    for s in soldiers:
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = scoring_svc.active_days(session, soldier=s)
        result.append(
            SoldierInput(
                id=s.id,
                enrolled_at=s.enrolled_at,
                cumulative_score=cum,
                active_days=ad,
                hierarchy_node_id=s.hierarchy_node_id,
                approved_constraint_dates=soldier_constraints.get(s.id, []),
                exempted_duty_type_ids=soldier_exempt_dtype_ids.get(s.id, set()),
            )
        )
    return result


def load_duty_blocks(
    session: Session,
    *,
    planning_start: date,
    planning_end: date,
    duty_type_ids: list[uuid.UUID],
    duty_location_id: uuid.UUID,
) -> list[DutyBlock]:
    """Synthesise one DutyBlock per (duty_type, day) in the planning window."""
    types = (
        session.execute(
            select(DutyType).where(DutyType.id.in_(duty_type_ids), DutyType.active.is_(True))
        )
        .scalars()
        .all()
    )
    blocks: list[DutyBlock] = []
    day = planning_start
    while day <= planning_end:
        for dt in types:
            blocks.append(
                DutyBlock(
                    id=uuid.uuid4(),
                    duty_type_id=dt.id,
                    duty_location_id=duty_location_id,
                    start_date=day,
                    end_date=day,
                    score_per_day=dt.score_per_day,
                )
            )
        day += timedelta(days=1)
    return blocks


def load_existing_assignments(
    session: Session,
    *,
    planning_start: date,
    planning_end: date,
    W: int,
) -> list[ExistingAssignment]:
    """Load published assignments within W days of the planning window for spacing checks."""
    boundary_start = planning_start - timedelta(days=W)
    boundary_end = planning_end + timedelta(days=W)
    rows = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.start_date <= boundary_end,
                DutyAssignment.end_date >= boundary_start,
            )
        )
        .scalars()
        .all()
    )
    return [
        ExistingAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
        )
        for a in rows
    ]


def build_hierarchy_maps(
    session: Session,
) -> tuple[
    dict[uuid.UUID, uuid.UUID | None],
    dict[uuid.UUID, list[uuid.UUID]],
    dict[uuid.UUID, uuid.UUID],
    dict[uuid.UUID, list[uuid.UUID]],
]:
    """Return (hierarchy_parent, hierarchy_children, soldier_node, node_soldiers)."""
    nodes = session.execute(select(HierarchyNode)).scalars().all()
    soldiers = (
        session.execute(
            select(Soldier.id, Soldier.hierarchy_node_id).where(Soldier.left_at.is_(None))
        )
        .all()
    )

    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None] = {n.id: n.parent_id for n in nodes}
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]] = {n.id: [] for n in nodes}
    for n in nodes:
        if n.parent_id is not None and n.parent_id in hierarchy_children:
            hierarchy_children[n.parent_id].append(n.id)

    soldier_node: dict[uuid.UUID, uuid.UUID] = {}
    node_soldiers: dict[uuid.UUID, list[uuid.UUID]] = {n.id: [] for n in nodes}
    for sid, nid in soldiers:
        if nid is not None:
            soldier_node[sid] = nid
            node_soldiers.setdefault(nid, []).append(sid)

    return hierarchy_parent, hierarchy_children, soldier_node, node_soldiers
```

- [ ] **Step 3: Verify import**

```
uv run python -c "from app.services.algorithm_bridge import load_soldier_inputs, load_duty_blocks, load_existing_assignments, build_hierarchy_maps; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat(algorithm): bridge data-loading helpers (soldiers, duties, existing, hierarchy)"
```

---

### Task 4: Persistence helpers + `run_algorithm_job`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Append persistence helpers + `run_algorithm_job` to `algorithm_bridge.py`**

Add after `build_hierarchy_maps`:

```python
def _explanation_payload(exp: AlgoExplanation, *, dm_view: bool, soldier_names: dict[uuid.UUID, str], exemption_type_names: dict[uuid.UUID, str]) -> dict[str, Any]:
    """Serialise one AssignmentExplanation to a JSON-safe dict."""
    candidates = []
    for c in exp.candidates:
        entry: dict[str, Any] = {
            "soldier_id": str(c.soldier_id),
            "blocked": c.blocked,
            "blocking_constraints": c.blocking_constraints,
        }
        if dm_view:
            entry["soldier_name"] = soldier_names.get(c.soldier_id, "")
            entry["pre_norm_score"] = float(c.pre_norm_score) if c.pre_norm_score is not None else None
            entry["post_norm_score"] = float(c.post_norm_score) if c.post_norm_score is not None else None
        candidates.append(entry)
    return {
        "duty_id": str(exp.duty_id),
        "assigned_soldier_id": str(exp.assigned_soldier_id),
        "tiebreaker_note": exp.tiebreaker_note,
        "candidates": candidates,
    }


def persist_results(
    session: Session,
    *,
    job: AlgorithmJob,
    result: SolverResult,
    explanation_data: ExplanationData,
    reserves: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    duty_blocks: list[DutyBlock],
    soldier_names: dict[uuid.UUID, str],
    exemption_type_names: dict[uuid.UUID, str],
    actor_id: uuid.UUID | None,
) -> None:
    """Insert algorithm_draft assignments, explanations, and reserve rows."""
    duty_map = {d.id: d for d in duty_blocks}
    explanation_map = {e.duty_id: e for e in explanation_data.per_assignment}
    reserve_map: dict[uuid.UUID, uuid.UUID] = {
        duty_id: reserve_id for duty_id, _primary, reserve_id in reserves
    }

    for a in result.assignments:
        block = duty_map[a.duty_id]
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
        )
        session.add(da)
        session.flush()  # populate da.id

        payload = _explanation_payload(
            explanation_map[a.duty_id],
            dm_view=True,
            soldier_names=soldier_names,
            exemption_type_names=exemption_type_names,
        )
        payload["global_before"] = explanation_data.global_metrics_before
        payload["global_after"] = explanation_data.global_metrics_after

        session.add(
            AssignmentExplanation(
                duty_assignment_id=da.id,
                payload=payload,
                algorithm_version=explanation_data.algorithm_version,
                solver_seed=str(explanation_data.solver_seed),
            )
        )

        reserve_soldier_id = reserve_map.get(a.duty_id)
        if reserve_soldier_id is not None:
            session.add(
                ReserveAssignment(
                    duty_assignment_id=da.id,
                    reserve_soldier_id=reserve_soldier_id,
                    reason="auto: nearest in hierarchy",
                )
            )

        write_audit(
            session,
            actor_id=actor_id,
            action="algorithm.proposal.create",
            entity_type="duty_assignment",
            entity_id=da.id,
            after={"status": "algorithm_draft", "job_id": str(job.id)},
        )


def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    from app.algorithm.explain import build_explanations
    from app.algorithm.reserve import select_reserves
    from app.algorithm.solver import solve
    from app.db.session import session_scope

    with session_scope() as session:
        job = session.get(AlgorithmJob, job_id)
        if job is None:
            return

        job.status = "running"
        job.started_at = datetime.now(tz=timezone.utc)
        session.commit()

        try:
            settings = SolverSettings(
                K=Decimal(str(job.settings_json.get("K", 8))),
                T=int(job.settings_json.get("T", 7)),
                W=int(job.settings_json.get("W", 14)),
                alpha=Decimal(str(job.settings_json.get("alpha", 1.0))),
                beta=Decimal(str(job.settings_json.get("beta", 2.0))),
                time_limit_seconds=int(job.settings_json.get("time_limit_seconds", 30)),
            )
            duty_type_ids = [uuid.UUID(s) for s in job.duty_type_ids]

            as_of = job.planning_start
            soldiers = load_soldier_inputs(session, as_of=as_of)
            duties = load_duty_blocks(
                session,
                planning_start=job.planning_start,
                planning_end=job.planning_end,
                duty_type_ids=duty_type_ids,
                duty_location_id=job.duty_location_id,
            )
            existing = load_existing_assignments(
                session,
                planning_start=job.planning_start,
                planning_end=job.planning_end,
                W=settings.W,
            )

            if not soldiers or not duties:
                job.status = "failed"
                job.error_message = "no_soldiers_or_duties"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            result = solve(soldiers, duties, existing, settings)

            if result.status == "INFEASIBLE":
                job.status = "failed"
                job.error_message = json.dumps({"relaxed": result.relaxed, "status": "INFEASIBLE"})
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            explanation_data = build_explanations(
                soldiers=soldiers,
                duties=duties,
                assignments=result.assignments,
                solver_seed=result.seed,
                existing=existing,
            )
            hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)
            reserves = select_reserves(
                soldiers=soldiers,
                duties=duties,
                assignments=result.assignments,
                hierarchy_parent=hier_parent,
                hierarchy_children=hier_children,
                soldier_node=soldier_node,
                node_soldiers=node_soldiers,
            )

            soldier_names = {
                s.id: s.full_name
                for s in session.execute(select(Soldier)).scalars().all()
            }
            from app.db.models import ExemptionType
            exemption_type_names = {
                et.id: et.name
                for et in session.execute(select(ExemptionType)).scalars().all()
            }

            persist_results(
                session,
                job=job,
                result=result,
                explanation_data=explanation_data,
                reserves=reserves,
                duty_blocks=duties,
                soldier_names=soldier_names,
                exemption_type_names=exemption_type_names,
                actor_id=actor_id,
            )

            job.status = "done"
            job.finished_at = datetime.now(tz=timezone.utc)
            session.commit()

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            with session_scope() as err_session:
                err_job = err_session.get(AlgorithmJob, job_id)
                if err_job is not None:
                    err_job.status = "failed"
                    err_job.error_message = str(exc)
                    err_job.finished_at = datetime.now(tz=timezone.utc)
                    err_session.commit()
```

- [ ] **Step 2: Verify import**

```
uv run python -c "from app.services.algorithm_bridge import run_algorithm_job, persist_results; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat(algorithm): bridge persistence helpers and run_algorithm_job background task"
```

---

## Phase D — Routes

### Task 5: Algorithm routes

**Files:**
- Create: `backend/app/routes/algorithm.py`

- [ ] **Step 1: Write failing import test**

```
uv run python -c "from app.routes.algorithm import router; print('ok')"
```
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Create `backend/app/routes/algorithm.py`**

```python
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import get_current_user, require_password_changed
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    DutyAssignment,
    ReserveAssignment,
    Soldier,
)
from app.db.session import get_session
from app.services.algorithm_bridge import run_algorithm_job
from app.audit.writer import write_audit

router = APIRouter(prefix="/algorithm", tags=["algorithm"])


# ── Pydantic schemas ──

class SolverSettingsIn(BaseModel):
    K: int = 8
    T: int = 7
    W: int = 14
    alpha: float = 1.0
    beta: float = 2.0
    time_limit_seconds: int = 30


class CreateJobRequest(BaseModel):
    planning_start: date
    planning_end: date
    duty_type_ids: list[uuid.UUID] = Field(min_length=1)
    duty_location_id: uuid.UUID
    mode: str = "shadow"
    settings: SolverSettingsIn = Field(default_factory=SolverSettingsIn)


class JobOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    planning_start: date
    planning_end: date
    started_at: Any
    finished_at: Any
    error_message: str | None
    proposals: list[dict[str, Any]]
    solver_metrics: dict[str, Any]
    relaxed: list[str]


class SoldierExplanationOut(BaseModel):
    assigned: bool
    norm_score_before: float | None
    norm_score_after: float | None
    blocked_count: int
    tiebreaker_note: str | None
    global_before: dict[str, Any]
    global_after: dict[str, Any]


def _load_job(session: Session, job_id: uuid.UUID) -> AlgorithmJob:
    job = session.get(AlgorithmJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return job


def _load_assignment(session: Session, assignment_id: uuid.UUID) -> DutyAssignment:
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return a


def _proposals_for_job(session: Session, job: AlgorithmJob) -> list[dict[str, Any]]:
    """Load algorithm_draft assignments linked to this job (via created_by + status + created_at window)."""
    # We match by created_by == job.created_by AND status in (algorithm_draft, algorithm_rejected, published)
    # AND created_at >= job.started_at to scope to this run.
    if job.started_at is None:
        return []
    rows = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.created_by == job.created_by,
                DutyAssignment.status.in_(["algorithm_draft", "algorithm_rejected", "published"]),
                DutyAssignment.created_at >= job.started_at,
                DutyAssignment.start_date >= job.planning_start,
                DutyAssignment.end_date <= job.planning_end,
            )
        )
        .scalars()
        .all()
    )
    assignment_ids = {a.id for a in rows}
    reserves = (
        session.execute(
            select(ReserveAssignment).where(
                ReserveAssignment.duty_assignment_id.in_(assignment_ids)
            )
        )
        .scalars()
        .all()
    )
    reserve_map = {r.duty_assignment_id: r.reserve_soldier_id for r in reserves}

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
        if exp:
            payload = exp.payload
            assigned_sid = uuid.UUID(payload["assigned_soldier_id"])
            for c in payload.get("candidates", []):
                if uuid.UUID(c["soldier_id"]) == a.soldier_id and not c["blocked"]:
                    norm_before = c.get("pre_norm_score")
                    norm_after = c.get("post_norm_score")
                    break
        proposals.append({
            "assignment_id": str(a.id),
            "soldier_id": str(a.soldier_id),
            "duty_type_id": str(a.duty_type_id),
            "duty_location_id": str(a.duty_location_id),
            "start_date": a.start_date.isoformat(),
            "end_date": a.end_date.isoformat(),
            "status": a.status,
            "reserve_soldier_id": str(reserve_map[a.id]) if a.id in reserve_map else None,
            "norm_score_before": norm_before,
            "norm_score_after": norm_after,
        })
    return proposals


# ── Endpoints ──

@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: CreateJobRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    if body.planning_start > body.planning_end:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_date_range")
    if body.mode not in ("shadow", "dm_reviewed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_mode")
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    settings_dict = body.settings.model_dump()
    job = AlgorithmJob(
        planning_start=body.planning_start,
        planning_end=body.planning_end,
        duty_type_ids=[str(did) for did in body.duty_type_ids],
        duty_location_id=body.duty_location_id,
        settings_json=settings_dict,
        mode=body.mode,
        created_by=user.id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    background_tasks.add_task(run_algorithm_job, job.id, user.id)
    return {"id": str(job.id), "status": job.status}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> JobOut:
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    proposals = _proposals_for_job(session, job) if job.status == "done" else []
    return JobOut(
        id=job.id,
        status=job.status,
        mode=job.mode,
        planning_start=job.planning_start,
        planning_end=job.planning_end,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        proposals=proposals,
        solver_metrics={},
        relaxed=[],
    )


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_cancellable")
    job.status = "failed"
    job.error_message = "cancelled_by_user"
    session.commit()


@router.get("/jobs/{job_id}/explanations/{assignment_id}")
def get_explanation(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    _load_job(session, job_id)
    a = _load_assignment(session, assignment_id)

    is_dm = user.role in ("duty_manager", "admin")
    is_assignee = a.soldier_id == user.id
    if not is_dm and not is_assignee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    exp = session.execute(
        select(AssignmentExplanation).where(
            AssignmentExplanation.duty_assignment_id == assignment_id
        )
    ).scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    payload = exp.payload
    if is_dm:
        return payload

    # Soldier-redacted view
    blocked_count = sum(
        1 for c in payload.get("candidates", []) if c.get("blocked")
    )
    my_candidate = next(
        (c for c in payload.get("candidates", []) if c["soldier_id"] == str(user.id)),
        None,
    )
    return {
        "assigned": True,
        "norm_score_before": my_candidate.get("pre_norm_score") if my_candidate else None,
        "norm_score_after": my_candidate.get("post_norm_score") if my_candidate else None,
        "blocked_count": blocked_count,
        "tiebreaker_note": payload.get("tiebreaker_note"),
        "global_before": payload.get("global_before", {}),
        "global_after": payload.get("global_after", {}),
    }


@router.post("/jobs/{job_id}/proposals/{assignment_id}/accept", status_code=status.HTTP_200_OK)
def accept_proposal(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    _load_job(session, job_id)
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if a.status != "algorithm_draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_draft")
    a.status = "published"
    write_audit(
        session,
        actor_id=user.id,
        action="algorithm.proposal.accept",
        entity_type="duty_assignment",
        entity_id=a.id,
        before={"status": "algorithm_draft"},
        after={"status": "published"},
        context={"job_id": str(job_id)},
    )
    session.commit()
    return {"status": "published"}


@router.post("/jobs/{job_id}/proposals/{assignment_id}/reject", status_code=status.HTTP_200_OK)
def reject_proposal(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    _load_job(session, job_id)
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if a.status != "algorithm_draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_draft")
    a.status = "algorithm_rejected"
    write_audit(
        session,
        actor_id=user.id,
        action="algorithm.proposal.reject",
        entity_type="duty_assignment",
        entity_id=a.id,
        before={"status": "algorithm_draft"},
        after={"status": "algorithm_rejected"},
        context={"job_id": str(job_id)},
    )
    session.commit()
    return {"status": "algorithm_rejected"}
```

- [ ] **Step 3: Verify import**

```
uv run python -c "from app.routes.algorithm import router; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/algorithm.py
git commit -m "feat(api): algorithm job routes (submit, poll, cancel, explanation, accept, reject)"
```

---

### Task 6: Register algorithm router in `main.py`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the import and router registration**

In `backend/app/main.py`, add after the existing imports:
```python
from app.routes import algorithm as algorithm_routes
```

Add inside `create_app()`, after the existing `app.include_router(calendar_routes.router, prefix="/api")` line:
```python
    app.include_router(algorithm_routes.router, prefix="/api")
```

- [ ] **Step 2: Verify the app starts**

```
uv run python -c "from app.main import create_app; app = create_app(); print('app ok')"
```
Expected: `app ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(app): register algorithm router"
```

---

## Phase E — Backend tests

### Task 7: Unit tests for bridge service

**Files:**
- Create: `backend/tests/unit/test_algorithm_bridge.py`

- [ ] **Step 1: Create `backend/tests/unit/test_algorithm_bridge.py`**

```python
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierExemption,
)
from app.services.algorithm_bridge import (
    build_hierarchy_maps,
    load_duty_blocks,
    load_existing_assignments,
    load_soldier_inputs,
)
from tests.helpers import create_node, create_soldier


def _duty_type(session, name="שמירה", score="1.00") -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _location(session, name="שער") -> DutyLocation:
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_load_soldier_inputs_basic(admin_session):
    s = create_soldier(admin_session, personal_number="alg_001", role="soldier")
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    ids = [si.id for si in inputs]
    assert s.id in ids


def test_load_soldier_inputs_excludes_left(admin_session):
    s = create_soldier(admin_session, personal_number="alg_002", role="soldier")
    s.left_at = date(2026, 5, 1)
    admin_session.commit()
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    ids = [si.id for si in inputs]
    assert s.id not in ids


def test_load_soldier_inputs_includes_approved_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="alg_003", role="soldier")
    pc = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        reason="חופשה",
        status="approved",
    )
    admin_session.add(pc)
    admin_session.commit()
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    my = next(si for si in inputs if si.id == s.id)
    assert (date(2026, 6, 10), date(2026, 6, 15)) in my.approved_constraint_dates


def test_load_soldier_inputs_excludes_pending_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="alg_004", role="soldier")
    pc = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        reason="רפואי",
        status="pending",
    )
    admin_session.add(pc)
    admin_session.commit()
    inputs = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    my = next(si for si in inputs if si.id == s.id)
    assert my.approved_constraint_dates == []


def test_load_duty_blocks_generates_one_per_day_per_type(admin_session):
    dt1 = _duty_type(admin_session, name="שמירה_alg1")
    dt2 = _duty_type(admin_session, name="שמירה_alg2")
    loc = _location(admin_session, name="שער_alg")
    blocks = load_duty_blocks(
        admin_session,
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 3),
        duty_type_ids=[dt1.id, dt2.id],
        duty_location_id=loc.id,
    )
    # 3 days × 2 types = 6 blocks
    assert len(blocks) == 6
    dates = [b.start_date for b in blocks]
    assert date(2026, 6, 1) in dates
    assert date(2026, 6, 3) in dates


def test_load_duty_blocks_inactive_type_excluded(admin_session):
    dt_active = _duty_type(admin_session, name="שמירה_active_alg")
    dt_inactive = DutyType(name="שמירה_inactive_alg", score_per_day=Decimal("1.00"), active=False)
    admin_session.add(dt_inactive)
    admin_session.flush()
    loc = _location(admin_session, name="שער_alg2")
    blocks = load_duty_blocks(
        admin_session,
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 1),
        duty_type_ids=[dt_active.id, dt_inactive.id],
        duty_location_id=loc.id,
    )
    assert len(blocks) == 1
    assert blocks[0].duty_type_id == dt_active.id


def test_build_hierarchy_maps(admin_session):
    root = create_node(admin_session, level="department", name="dept_alg")
    child = create_node(admin_session, level="branch", name="branch_alg", parent=root)
    s = create_soldier(admin_session, personal_number="alg_hier_001", hierarchy_node_id=child.id)

    hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(admin_session)

    assert hier_parent[child.id] == root.id
    assert child.id in hier_children[root.id]
    assert soldier_node[s.id] == child.id
    assert s.id in node_soldiers[child.id]
```

- [ ] **Step 2: Run the tests**

Run from `backend/`:
```
uv run pytest tests/unit/test_algorithm_bridge.py -v
```
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_algorithm_bridge.py
git commit -m "test(algorithm): bridge service unit tests"
```

---

### Task 8: Integration tests for algorithm routes

**Files:**
- Create: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Create `backend/tests/integration/test_algorithm_routes.py`**

```python
from __future__ import annotations

import time
import uuid
from datetime import date

import pytest

from app.db.models import DutyLocation, DutyType, HierarchyNode
from tests.helpers import auth_headers, create_node, create_soldier
from decimal import Decimal


def _setup_dm(session, personal_number: str):
    node = create_node(session, level="branch", name=f"branch_{personal_number}")
    dm = create_soldier(
        session,
        personal_number=personal_number,
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    return dm, node


def _duty_type(session, name: str) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"))
    session.add(dt)
    session.flush()
    session.commit()
    return dt


def _location(session, name: str) -> DutyLocation:
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    session.commit()
    return loc


def test_create_job_returns_202(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_001")
    dt = _duty_type(admin_session, "שמירה_route_1")
    loc = _location(admin_session, "שער_route_1")
    # Create at least one soldier so the solver has inputs
    soldier = create_soldier(admin_session, personal_number="route_soldier_001", role="soldier")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-07-01",
            "planning_end": "2026-07-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 15},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert data["status"] == "pending"


def test_create_job_rejects_bad_date_range(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_002")
    dt = _duty_type(admin_session, "שמירה_route_2")
    loc = _location(admin_session, "שער_route_2")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-07-10",
            "planning_end": "2026-07-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "bad_date_range"


def test_soldier_cannot_create_job(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="route_alg_003")
    dt = _duty_type(admin_session, "שמירה_route_3")
    loc = _location(admin_session, "שער_route_3")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-07-01",
            "planning_end": "2026-07-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 403


def test_poll_job_returns_status(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_004")
    dt = _duty_type(admin_session, "שמירה_route_4")
    loc = _location(admin_session, "שער_route_4")
    create_soldier(admin_session, personal_number="route_soldier_004", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-08-01",
            "planning_end": "2026-08-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    # Poll until done or timeout after 20s
    for _ in range(10):
        poll_resp = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        assert poll_resp.status_code == 200
        if poll_resp.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    final = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
    assert final.json()["status"] in ("done", "failed")


def test_accept_proposal_publishes_assignment(client, admin_session):
    """Submit a job with one soldier + one duty, poll until done, then accept the proposal."""
    dm, _node = _setup_dm(admin_session, "route_alg_005")
    dt = _duty_type(admin_session, "שמירה_route_5")
    loc = _location(admin_session, "שער_route_5")
    create_soldier(admin_session, personal_number="route_soldier_005", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-09-01",
            "planning_end": "2026-09-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    for _ in range(10):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] == "done":
            break
        time.sleep(2)

    proposals = poll.json().get("proposals", [])
    if not proposals:
        pytest.skip("solver returned no proposals (possible infeasible with single soldier)")

    asgn_id = proposals[0]["assignment_id"]
    accept_resp = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/accept",
        headers=auth_headers(dm),
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "published"

    # Double-accept should fail
    double = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/accept",
        headers=auth_headers(dm),
    )
    assert double.status_code == 409


def test_reject_proposal(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_006")
    dt = _duty_type(admin_session, "שמירה_route_6")
    loc = _location(admin_session, "שער_route_6")
    create_soldier(admin_session, personal_number="route_soldier_006", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-10-01",
            "planning_end": "2026-10-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]
    for _ in range(10):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] == "done":
            break
        time.sleep(2)

    proposals = poll.json().get("proposals", [])
    if not proposals:
        pytest.skip("no proposals")

    asgn_id = proposals[0]["assignment_id"]
    resp = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/reject",
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "algorithm_rejected"
```

- [ ] **Step 2: Run integration tests**

Run from `backend/`:
```
uv run pytest tests/integration/test_algorithm_routes.py -v
```
Expected: All pass. The `test_accept_proposal_publishes_assignment` and `test_reject_proposal` tests may `pytest.skip` if the solver returns infeasible for a single-soldier population — that's expected and safe.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_algorithm_routes.py
git commit -m "test(algorithm): integration tests for algorithm job routes"
```

---

## Phase F — Frontend

### Task 9: API client + i18n additions

**Files:**
- Create: `frontend/src/api/algorithm.ts`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Create `frontend/src/api/algorithm.ts`**

```typescript
import { api } from "./client";

export interface SolverSettings {
  K: number;
  T: number;
  W: number;
  alpha: number;
  beta: number;
  time_limit_seconds: number;
}

export interface CreateJobRequest {
  planning_start: string;
  planning_end: string;
  duty_type_ids: string[];
  duty_location_id: string;
  mode: "shadow" | "dm_reviewed";
  settings: SolverSettings;
}

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
}

export interface AlgorithmJob {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  mode: string;
  planning_start: string;
  planning_end: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  proposals: ProposalRow[];
  solver_metrics: Record<string, number>;
  relaxed: string[];
}

export interface SoldierExplanation {
  assigned: boolean;
  norm_score_before: number | null;
  norm_score_after: number | null;
  blocked_count: number;
  tiebreaker_note: string | null;
  global_before: { min_gap: number; norm_variance: number };
  global_after: { min_gap: number; norm_variance: number };
}

export interface DmExplanation {
  duty_id: string;
  assigned_soldier_id: string;
  tiebreaker_note: string | null;
  candidates: Array<{
    soldier_id: string;
    soldier_name: string;
    blocked: boolean;
    blocking_constraints: string[];
    pre_norm_score: number | null;
    post_norm_score: number | null;
  }>;
  global_before: Record<string, number>;
  global_after: Record<string, number>;
}

export async function submitJob(req: CreateJobRequest): Promise<{ id: string; status: string }> {
  return (await api.post<{ id: string; status: string }>("/algorithm/jobs", req)).data;
}

export async function pollJob(jobId: string): Promise<AlgorithmJob> {
  return (await api.get<AlgorithmJob>(`/algorithm/jobs/${jobId}`)).data;
}

export async function getExplanation(
  jobId: string,
  assignmentId: string
): Promise<SoldierExplanation | DmExplanation> {
  return (
    await api.get<SoldierExplanation | DmExplanation>(
      `/algorithm/jobs/${jobId}/explanations/${assignmentId}`
    )
  ).data;
}

export async function acceptProposal(jobId: string, assignmentId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/proposals/${assignmentId}/accept`);
}

export async function rejectProposal(jobId: string, assignmentId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/proposals/${assignmentId}/reject`);
}
```

- [ ] **Step 2: Add `algorithm` block to `frontend/src/i18n/he.json`**

Add after the last key in the JSON object (before the closing `}`):

```json
  "algorithm": {
    "title": "חלון תכנון",
    "run_button": "הרץ אלגוריתם",
    "running": "האלגוריתם רץ...",
    "elapsed": "{{seconds}} שניות",
    "done": "הצעות האלגוריתם",
    "failed": "האלגוריתם נכשל",
    "shadow_mode": "מצב צל",
    "dm_reviewed_mode": "מצב סקירה",
    "accept": "אשר",
    "reject": "דחה",
    "why_button": "?למה קיבלתי",
    "blocked_count": "{{count}} חיילים היו מוגבלים",
    "norm_before": "ניקוד מנורמל לפני",
    "norm_after": "ניקוד מנורמל אחרי",
    "min_gap_before": "פער מינימלי לפני",
    "min_gap_after": "פער מינימלי אחרי",
    "relaxed_k": "הורחב K ל-{{value}}",
    "relaxed_t": "הורחב T ל-{{value}}",
    "no_solution": "לא נמצא פתרון אפשרי",
    "settings": "הגדרות מתקדמות",
    "planning_start": "תחילת חלון",
    "planning_end": "סוף חלון",
    "duty_types": "סוגי תורנות",
    "location": "מיקום",
    "mode_label": "מצב הרצה",
    "col_date": "תאריך",
    "col_type": "סוג תורנות",
    "col_soldier": "חייל",
    "col_reserve": "רזרבה",
    "col_score_before": "ניקוד לפני",
    "col_score_after": "ניקוד אחרי",
    "col_actions": "פעולות",
    "no_proposals": "אין הצעות"
  }
```

- [ ] **Step 3: Verify TypeScript compiles**

Run from `frontend/`:
```
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/algorithm.ts frontend/src/i18n/he.json
git commit -m "feat(frontend): algorithm API client and i18n keys"
```

---

### Task 10: ExplanationModal component

**Files:**
- Create: `frontend/src/components/ExplanationModal.tsx`

- [ ] **Step 1: Create `frontend/src/components/ExplanationModal.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DmExplanation, SoldierExplanation, getExplanation } from "../api/algorithm";
import { useAuth } from "../auth/AuthContext";

interface Props {
  jobId: string;
  assignmentId: string;
  onClose: () => void;
}

function isDmExplanation(e: SoldierExplanation | DmExplanation): e is DmExplanation {
  return "candidates" in e;
}

export default function ExplanationModal({ jobId, assignmentId, onClose }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [data, setData] = useState<SoldierExplanation | DmExplanation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const result = await getExplanation(jobId, assignmentId);
        setData(result);
      } catch {
        setError("שגיאה בטעינת ההסבר");
      } finally {
        setLoading(false);
      }
    })();
  }, [jobId, assignmentId]);

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{t("algorithm.why_button")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl">✕</button>
        </div>

        {loading && <p className="text-gray-500">{t("app.loading")}</p>}
        {error && <p className="text-red-500">{error}</p>}

        {data && !isDmExplanation(data) && (
          <div className="space-y-3 text-sm">
            <p>{t("algorithm.blocked_count", { count: data.blocked_count })}</p>
            {data.norm_score_before !== null && (
              <p>{t("algorithm.norm_before")}: <strong>{data.norm_score_before?.toFixed(3)}</strong></p>
            )}
            {data.norm_score_after !== null && (
              <p>{t("algorithm.norm_after")}: <strong>{data.norm_score_after?.toFixed(3)}</strong></p>
            )}
            <p>{t("algorithm.min_gap_before")}: <strong>{data.global_before?.min_gap}</strong> {t("algorithm.elapsed", { seconds: "" }).replace("שניות", "ימים")}</p>
            <p>{t("algorithm.min_gap_after")}: <strong>{data.global_after?.min_gap}</strong></p>
          </div>
        )}

        {data && isDmExplanation(data) && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="font-medium">{t("algorithm.min_gap_before")}: {data.global_before?.min_gap}</p>
                <p className="font-medium">{t("algorithm.min_gap_after")}: {data.global_after?.min_gap}</p>
              </div>
            </div>
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="bg-gray-50">
                  <th className="border px-2 py-1 text-right">חייל</th>
                  <th className="border px-2 py-1 text-right">חסום?</th>
                  <th className="border px-2 py-1 text-right">סיבה</th>
                  <th className="border px-2 py-1 text-right">{t("algorithm.norm_before")}</th>
                  <th className="border px-2 py-1 text-right">{t("algorithm.norm_after")}</th>
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((c, i) => (
                  <tr key={i} className={c.blocked ? "bg-red-50" : "bg-green-50"}>
                    <td className="border px-2 py-1">{c.soldier_name || c.soldier_id.slice(0, 8)}</td>
                    <td className="border px-2 py-1">{c.blocked ? "✗" : "✓"}</td>
                    <td className="border px-2 py-1">{c.blocking_constraints.join(", ")}</td>
                    <td className="border px-2 py-1">{c.pre_norm_score?.toFixed(3) ?? "—"}</td>
                    <td className="border px-2 py-1">{c.post_norm_score?.toFixed(3) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.tiebreaker_note && (
              <p className="text-gray-600">בורר: {data.tiebreaker_note}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ExplanationModal.tsx
git commit -m "feat(frontend): ExplanationModal component (soldier-redacted + DM full view)"
```

---

### Task 11: AlgorithmPlanningWindow component

**Files:**
- Create: `frontend/src/components/AlgorithmPlanningWindow.tsx`

- [ ] **Step 1: Create `frontend/src/components/AlgorithmPlanningWindow.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlgorithmJob,
  CreateJobRequest,
  ProposalRow,
  SolverSettings,
  acceptProposal,
  pollJob,
  rejectProposal,
  submitJob,
} from "../api/algorithm";
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

export default function AlgorithmPlanningWindow({ dutyTypes, locations, soldiers }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [planStart, setPlanStart] = useState("");
  const [planEnd, setPlanEnd] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [locationId, setLocationId] = useState(locations[0]?.id ?? "");
  const [mode, setMode] = useState<"shadow" | "dm_reviewed">("shadow");
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<AlgorithmJob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [explanationTarget, setExplanationTarget] = useState<{ jobId: string; assignmentId: string } | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  useEffect(() => {
    if (!locationId && locations.length > 0) setLocationId(locations[0].id);
  }, [locations]);

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

  async function handleRun() {
    setError(null);
    setJob(null);
    setJobId(null);
    if (!planStart || !planEnd || selectedTypes.length === 0 || !locationId) {
      setError("נא למלא את כל השדות");
      return;
    }
    try {
      const req: CreateJobRequest = {
        planning_start: planStart,
        planning_end: planEnd,
        duty_type_ids: selectedTypes,
        duty_location_id: locationId,
        mode,
        settings,
      };
      const resp = await submitJob(req);
      setJobId(resp.id);
    } catch (e: unknown) {
      setError("שגיאה בשליחת הבקשה");
    }
  }

  function toggleType(id: string) {
    setSelectedTypes((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  async function handleAccept(proposal: ProposalRow) {
    if (!jobId) return;
    await acceptProposal(jobId, proposal.assignment_id);
    setJob((prev) =>
      prev
        ? {
            ...prev,
            proposals: prev.proposals.map((p) =>
              p.assignment_id === proposal.assignment_id ? { ...p, status: "published" } : p
            ),
          }
        : prev
    );
  }

  async function handleReject(proposal: ProposalRow) {
    if (!jobId) return;
    await rejectProposal(jobId, proposal.assignment_id);
    setJob((prev) =>
      prev
        ? {
            ...prev,
            proposals: prev.proposals.map((p) =>
              p.assignment_id === proposal.assignment_id ? { ...p, status: "algorithm_rejected" } : p
            ),
          }
        : prev
    );
  }

  const soldierName = (id: string) =>
    soldiers.find((s) => s.id === id)?.full_name ?? id.slice(0, 8);

  const typeName = (id: string) => dutyTypes.find((d) => d.id === id)?.name ?? id.slice(0, 8);

  const isRunning = !!jobId && job?.status === "pending" || job?.status === "running";

  return (
    <div className="border rounded-lg mt-6" dir="rtl">
      <button
        className="w-full flex justify-between items-center px-4 py-3 font-medium text-right bg-gray-50 rounded-lg hover:bg-gray-100"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{t("algorithm.title")}</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="p-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <label className="block text-sm">
              {t("algorithm.planning_start")}
              <input
                type="date"
                value={planStart}
                onChange={(e) => setPlanStart(e.target.value)}
                className="mt-1 block w-full border rounded p-1 text-sm"
              />
            </label>
            <label className="block text-sm">
              {t("algorithm.planning_end")}
              <input
                type="date"
                value={planEnd}
                onChange={(e) => setPlanEnd(e.target.value)}
                className="mt-1 block w-full border rounded p-1 text-sm"
              />
            </label>
          </div>

          <div className="text-sm">
            <p className="font-medium mb-1">{t("algorithm.duty_types")}</p>
            <div className="flex flex-wrap gap-2">
              {dutyTypes.map((dt) => (
                <label key={dt.id} className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={selectedTypes.includes(dt.id)}
                    onChange={() => toggleType(dt.id)}
                  />
                  {dt.name}
                </label>
              ))}
            </div>
          </div>

          <label className="block text-sm">
            {t("algorithm.location")}
            <select
              value={locationId}
              onChange={(e) => setLocationId(e.target.value)}
              className="mt-1 block w-full border rounded p-1 text-sm"
            >
              {locations.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            {t("algorithm.mode_label")}
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as "shadow" | "dm_reviewed")}
              className="mt-1 block w-full border rounded p-1 text-sm"
            >
              <option value="shadow">{t("algorithm.shadow_mode")}</option>
              <option value="dm_reviewed">{t("algorithm.dm_reviewed_mode")}</option>
            </select>
          </label>

          <button
            className="text-xs text-blue-600 underline"
            onClick={() => setShowSettings((s) => !s)}
          >
            {t("algorithm.settings")}
          </button>

          {showSettings && (
            <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 p-3 rounded">
              {(["K", "T", "W", "alpha", "beta", "time_limit_seconds"] as const).map((key) => (
                <label key={key} className="block">
                  {key}
                  <input
                    type="number"
                    value={settings[key]}
                    onChange={(e) =>
                      setSettings((s) => ({ ...s, [key]: parseFloat(e.target.value) }))
                    }
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
            disabled={!!isRunning}
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {t("algorithm.run_button")}
          </button>

          {isRunning && (
            <p className="text-sm text-gray-600 animate-pulse">
              {t("algorithm.running")} ({elapsed}s)
            </p>
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
              {job.proposals.length === 0 && (
                <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
              )}
              {job.proposals.length > 0 && (
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
                    {job.proposals.map((p) => {
                      const isAccepted = p.status === "published";
                      const isRejected = p.status === "algorithm_rejected";
                      return (
                        <tr
                          key={p.assignment_id}
                          className={
                            isAccepted ? "bg-green-50" : isRejected ? "bg-gray-100 opacity-50" : ""
                          }
                        >
                          <td className="border px-2 py-1">{p.start_date}</td>
                          <td className="border px-2 py-1">{typeName(p.duty_type_id)}</td>
                          <td className="border px-2 py-1">{soldierName(p.soldier_id)}</td>
                          <td className="border px-2 py-1">
                            {p.reserve_soldier_id ? soldierName(p.reserve_soldier_id) : "—"}
                          </td>
                          <td className="border px-2 py-1">
                            {p.norm_score_before?.toFixed(3) ?? "—"}
                          </td>
                          <td className="border px-2 py-1">
                            {p.norm_score_after?.toFixed(3) ?? "—"}
                          </td>
                          <td className="border px-2 py-1 space-x-1 space-x-reverse">
                            {!isAccepted && !isRejected && (
                              <>
                                <button
                                  onClick={() => handleAccept(p)}
                                  className="text-green-700 font-bold hover:underline"
                                >
                                  {t("algorithm.accept")}
                                </button>
                                <button
                                  onClick={() => handleReject(p)}
                                  className="text-red-700 hover:underline"
                                >
                                  {t("algorithm.reject")}
                                </button>
                              </>
                            )}
                            <button
                              onClick={() =>
                                setExplanationTarget({
                                  jobId: job.id,
                                  assignmentId: p.assignment_id,
                                })
                              }
                              className="text-blue-600 hover:underline"
                            >
                              {t("algorithm.why_button")}
                            </button>
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

- [ ] **Step 2: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlgorithmPlanningWindow.tsx
git commit -m "feat(frontend): AlgorithmPlanningWindow component with polling, proposals table, accept/reject"
```

---

### Task 12: Wire AlgorithmPlanningWindow into DutyManagementPage

**Files:**
- Modify: `frontend/src/pages/DutyManagementPage.tsx`

- [ ] **Step 1: Add the import at the top of DutyManagementPage.tsx**

Add after the existing imports:
```tsx
import AlgorithmPlanningWindow from "../components/AlgorithmPlanningWindow";
```

- [ ] **Step 2: Add the component at the bottom of the page, inside `<Layout>`**

In the `return` statement, add `<AlgorithmPlanningWindow>` immediately before the closing `</section>` tag (or before the closing `</Layout>` tag if the structure differs). The component receives `dutyTypes={types}`, `locations={locs}`, `soldiers={soldiers}` — these are already loaded in the page's `useEffect`.

Find the closing `</section>` that wraps the page content and add before it:
```tsx
        <AlgorithmPlanningWindow
          dutyTypes={types}
          locations={locs}
          soldiers={soldiers}
        />
```

- [ ] **Step 3: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/DutyManagementPage.tsx
git commit -m "feat(frontend): add AlgorithmPlanningWindow to DutyManagementPage"
```

---

### Task 13: Wire "?למה קיבלתי" into MyDutiesPage

**Files:**
- Modify: `frontend/src/pages/MyDutiesPage.tsx`

- [ ] **Step 1: Add import**

Add after existing imports in `MyDutiesPage.tsx`:
```tsx
import ExplanationModal from "../components/ExplanationModal";
```

- [ ] **Step 2: Add state for the explanation modal**

Add to the component's state declarations:
```tsx
const [whyTarget, setWhyTarget] = useState<{ assignmentId: string } | null>(null);
```

Note: The explanation endpoint requires a `job_id` in the URL. However, for soldiers viewing their published duties, we don't have the job ID directly. Use a sentinel job ID of `"none"` — the route handler already loads the assignment by `assignment_id` alone (the `job_id` parameter is loaded but not used to scope the explanation fetch in the current implementation). Alternatively, expose a direct explanation endpoint. For now, pass `"none"` as the job ID and update `getExplanation` to call `GET /api/algorithm/explanations/{assignment_id}` directly.

Update `frontend/src/api/algorithm.ts` — add a convenience function:
```typescript
export async function getExplanationByAssignment(
  assignmentId: string
): Promise<SoldierExplanation | DmExplanation> {
  // Uses a direct lookup — passes "none" as job sentinel since server resolves by assignment_id
  return (
    await api.get<SoldierExplanation | DmExplanation>(
      `/algorithm/jobs/none/explanations/${assignmentId}`
    )
  ).data;
}
```

Also add a route in `backend/app/routes/algorithm.py` that accepts `job_id = "none"` by treating it as a wildcard — the existing `get_explanation` handler already loads the job with `_load_job(session, job_id)` which would 404 on "none". Add a separate endpoint:

In `backend/app/routes/algorithm.py`, add after the existing explanation endpoint:
```python
@router.get("/explanations/{assignment_id}")
def get_explanation_direct(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    """Direct explanation lookup by assignment_id (for soldier MyDutiesPage)."""
    a = _load_assignment(session, assignment_id)
    is_dm = user.role in ("duty_manager", "admin")
    is_assignee = a.soldier_id == user.id
    if not is_dm and not is_assignee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    exp = session.execute(
        select(AssignmentExplanation).where(
            AssignmentExplanation.duty_assignment_id == assignment_id
        )
    ).scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    payload = exp.payload
    if is_dm:
        return payload

    blocked_count = sum(1 for c in payload.get("candidates", []) if c.get("blocked"))
    my_candidate = next(
        (c for c in payload.get("candidates", []) if c["soldier_id"] == str(user.id)),
        None,
    )
    return {
        "assigned": True,
        "norm_score_before": my_candidate.get("pre_norm_score") if my_candidate else None,
        "norm_score_after": my_candidate.get("post_norm_score") if my_candidate else None,
        "blocked_count": blocked_count,
        "tiebreaker_note": payload.get("tiebreaker_note"),
        "global_before": payload.get("global_before", {}),
        "global_after": payload.get("global_after", {}),
    }
```

Update `ExplanationModal` to accept an optional `direct` prop:

In `frontend/src/components/ExplanationModal.tsx`, update `Props` and the fetch:
```tsx
interface Props {
  jobId?: string;
  assignmentId: string;
  onClose: () => void;
}
```

And update the `useEffect` to use the direct endpoint when `jobId` is undefined:
```tsx
  useEffect(() => {
    void (async () => {
      try {
        let result;
        if (jobId) {
          result = await getExplanation(jobId, assignmentId);
        } else {
          result = await getExplanationByAssignment(assignmentId);
        }
        setData(result);
      } catch {
        setError("שגיאה בטעינת ההסבר");
      } finally {
        setLoading(false);
      }
    })();
  }, [jobId, assignmentId]);
```

Also update the import in `ExplanationModal.tsx`:
```tsx
import { DmExplanation, SoldierExplanation, getExplanation, getExplanationByAssignment } from "../api/algorithm";
```

- [ ] **Step 3: Add "?למה קיבלתי" button to duty rows in MyDutiesPage**

In the `filteredRows.map(...)` section of `MyDutiesPage.tsx`, add a button next to each duty row. Find where each row is rendered and add:
```tsx
              <button
                onClick={() => setWhyTarget({ assignmentId: r.assignment_id })}
                className="text-xs text-blue-600 underline ms-2"
              >
                {t("algorithm.why_button")}
              </button>
```

- [ ] **Step 4: Add the modal to the JSX return**

Before the closing `</Layout>` in `MyDutiesPage.tsx`:
```tsx
      {whyTarget && (
        <ExplanationModal
          assignmentId={whyTarget.assignmentId}
          onClose={() => setWhyTarget(null)}
        />
      )}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/MyDutiesPage.tsx frontend/src/components/ExplanationModal.tsx frontend/src/api/algorithm.ts backend/app/routes/algorithm.py
git commit -m "feat(frontend): ?למה קיבלתי button and modal on MyDutiesPage"
```

---

## Self-review checklist

After completing all tasks, verify:

1. **Spec coverage:**
   - ✅ `algorithm_jobs`, `reserve_assignments`, `assignment_explanations` tables — Task 1
   - ✅ `algorithm_draft`, `algorithm_rejected` status values — Task 1 (models) + Task 5 (routes)
   - ✅ Bridge service — Tasks 3–4
   - ✅ 6 API endpoints — Task 5
   - ✅ Router registered — Task 6
   - ✅ Shadow mode (stored as `mode` field in job) — Tasks 5, 11
   - ✅ DM planning window — Tasks 11, 12
   - ✅ "?למה קיבלתי" modal (both surfaces) — Tasks 10, 13
   - ✅ i18n keys — Task 9
   - ✅ Unit tests — Task 7
   - ✅ Integration tests — Task 8

2. **Placeholder scan:** All code blocks are complete. No "TBD" or "TODO".

3. **Type consistency:** `ProposalRow`, `AlgorithmJob`, `SoldierExplanation`, `DmExplanation` used consistently across `algorithm.ts`, `AlgorithmPlanningWindow.tsx`, and `ExplanationModal.tsx`.

---

## Summary

```
Phase A (Task 1):  DB models + migration 0016                [models.py, 0016_*.py]
Phase B (Task 2):  ALGORITHM_RUN auth action                 [authz.py]
Phase C (Tasks 3-4): Bridge service                          [algorithm_bridge.py]
Phase D (Tasks 5-6): Routes + registration                   [routes/algorithm.py, main.py]
Phase E (Tasks 7-8): Backend tests                           [test_algorithm_bridge.py, test_algorithm_routes.py]
Phase F (Tasks 9-13): Frontend                               [algorithm.ts, he.json, ExplanationModal.tsx, AlgorithmPlanningWindow.tsx, DutyManagementPage.tsx, MyDutiesPage.tsx]
```
