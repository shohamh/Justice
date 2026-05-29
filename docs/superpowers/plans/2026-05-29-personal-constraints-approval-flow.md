# Personal Constraints + Approval Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Full-stack personal_constraints CRUD, approval lifecycle, cap enforcement, and UI pages.

**Architecture:** Backend-first (migration → ORM → service → routes → authz), then frontend (API client → pages → layout → i18n). Follows the exact patterns of the existing exemptions system.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + Alembic + Postgres 16 (backend), React 18 + Vite + TypeScript + TailwindCSS (frontend), pytest + testcontainers (tests).

---

### File structure

**Backend:**
- Create: `backend/alembic/versions/0015_create_personal_constraints.py`
- Modify: `backend/app/db/models.py` — add PersonalConstraint model
- Modify: `backend/app/auth/authz.py` — add 3 action constants
- Create: `backend/app/services/constraints.py`
- Create: `backend/app/routes/constraints.py`
- Modify: `backend/app/main.py` — register router
- Create: `backend/tests/unit/test_constraints_service.py`
- Create: `backend/tests/integration/test_constraints_api.py`

**Frontend:**
- Create: `frontend/src/api/constraints.ts`
- Create: `frontend/src/pages/MyRequestsPage.tsx`
- Create: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/i18n/he.json`

---

### Task 1: Migration + ORM model

**Files:**
- Create: `backend/alembic/versions/0015_create_personal_constraints.py`
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Write the migration**

```python
"""create personal_constraints table

Revision ID: 0015
Revises: 0014
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE constraint_status AS ENUM ('pending','approved','rejected')")
    op.create_table(
        "personal_constraints",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", sa.UUID(), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.UUID(), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_pc_soldier", "personal_constraints", ["soldier_id"])
    op.create_index("idx_pc_status", "personal_constraints", ["status"])


def downgrade() -> None:
    op.drop_table("personal_constraints")
    op.execute("DROP TYPE constraint_status")
```

- [ ] **Step 2: Add ORM model to models.py**

Insert after `ScoreAdjustment` class:

```python
class PersonalConstraint(Base):
    __tablename__ = "personal_constraints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending", default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 3: Run migration check**

```bash
cd backend && alembic check
```

Expected: "No new revisions found" (migration up to date) — or "New revisions found" if the migration hasn't been discovered. Run `alembic upgrade head` to apply.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0015_create_personal_constraints.py backend/app/db/models.py
git commit -m "feat: add PersonalConstraint model and migration"
```

---

### Task 2: Authz actions

**Files:**
- Modify: `backend/app/auth/authz.py`

- [ ] **Step 1: Add action constants to Action class**

Add after `SCORE_ADJUST = "score.adjust"`:

```python
    CONSTRAINT_SUBMIT = "constraint.submit"
    CONSTRAINT_READ = "constraint.read"
    CONSTRAINT_APPROVE = "constraint.approve"
```

- [ ] **Step 2: Add to DM and commander action sets**

Add to `_DM_ACTIONS`:
```python
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
```

Add to `_COMMANDER_ACTIONS`:
```python
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/auth/authz.py
git commit -m "feat: add CONSTRAINT_READ and CONSTRAINT_APPROVE authz actions"
```

---

### Task 3: Service layer

**Files:**
- Create: `backend/app/services/constraints.py`

- [ ] **Step 1: Write the service**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import PersonalConstraint, Soldier
from app.settings import get_settings


class ConstraintError(Exception):
    """Raised on an invalid constraint operation."""


def _future_cap_used(session: Session, soldier_id: uuid.UUID) -> int:
    """Sum of (end-start+1) for pending+approved constraints that end today or later."""
    today = date.today()
    rows = list(
        session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.soldier_id == soldier_id,
                PersonalConstraint.end_date >= today,
                PersonalConstraint.status.in_(["pending", "approved"]),
            )
        )
        .scalars()
        .all()
    )
    return sum((r.end_date - r.start_date).days + 1 for r in rows)


def submit_constraint(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> PersonalConstraint:
    if session.get(Soldier, soldier_id) is None:
        raise ConstraintError("soldier_not_found")
    if end_date < start_date:
        raise ConstraintError("bad_date_range")
    if start_date < date.today():
        raise ConstraintError("start_date_in_past")

    settings = get_settings()
    cap_days = int(settings.get("constraints.personal_cap_days", 15))
    used = _future_cap_used(session, soldier_id)
    requested = (end_date - start_date).days + 1
    if used + requested > cap_days:
        raise ConstraintError("cap_exceeded")

    require_approval = settings.get("constraints.require_manager_approval", True)
    if require_approval:
        c = PersonalConstraint(
            soldier_id=soldier_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status="pending",
        )
    else:
        now = datetime.now(timezone.utc)
        c = PersonalConstraint(
            soldier_id=soldier_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status="approved",
            decided_by=actor_id,
            decided_at=now,
        )

    session.add(c)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.submit",
        entity_type="personal_constraint",
        entity_id=c.id,
        after={
            "soldier_id": str(soldier_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "reason": reason,
            "status": c.status,
        },
    )
    return c


def approve_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    decision_note: str | None = None,
) -> PersonalConstraint:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status != "pending":
        raise ConstraintError("not_pending")
    c.status = "approved"
    c.decided_by = actor_id
    c.decided_at = datetime.now(timezone.utc)
    c.decision_note = decision_note
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.approve",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": "pending"},
        after={"status": "approved", "decision_note": decision_note},
    )
    return c


def reject_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    decision_note: str,
) -> PersonalConstraint:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status != "pending":
        raise ConstraintError("not_pending")
    c.status = "rejected"
    c.decided_by = actor_id
    c.decided_at = datetime.now(timezone.utc)
    c.decision_note = decision_note
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.reject",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": "pending"},
        after={"status": "rejected", "decision_note": decision_note},
    )
    return c


def cancel_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status != "pending":
        raise ConstraintError("not_pending")
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.cancel",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": "pending"},
        after={"deleted": True},
    )
    session.delete(c)


def list_constraints(session: Session, *, soldier_id: uuid.UUID) -> list[PersonalConstraint]:
    return list(
        session.execute(
            select(PersonalConstraint)
            .where(PersonalConstraint.soldier_id == soldier_id)
            .order_by(PersonalConstraint.created_at.desc())
        )
        .scalars()
        .all()
    )


def list_pending_approvals(
    session: Session,
    *,
    node_ids: set[uuid.UUID],
) -> list[PersonalConstraint]:
    """All pending constraints whose soldier's hierarchy_node is in scope."""
    from app.db.models import HierarchyNode

    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(node_ids)))
        .subquery()
    )
    return list(
        session.execute(
            select(PersonalConstraint)
            .where(
                PersonalConstraint.status == "pending",
                PersonalConstraint.soldier_id.in_(
                    select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
                ),
            )
            .order_by(PersonalConstraint.created_at.asc())
        )
        .scalars()
        .all()
    )


def pending_approval_count(session: Session, *, node_ids: set[uuid.UUID]) -> int:
    from app.db.models import HierarchyNode

    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(node_ids)))
        .subquery()
    )
    return (
        session.execute(
            select(PersonalConstraint)
            .where(
                PersonalConstraint.status == "pending",
                PersonalConstraint.soldier_id.in_(
                    select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
                ),
            )
        )
        .scalars()
        .count()
    )


def get_approved_constraint_dates(
    session: Session, *, soldier_id: uuid.UUID
) -> list[tuple[date, date]]:
    today = date.today()
    rows = list(
        session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.soldier_id == soldier_id,
                PersonalConstraint.status == "approved",
                PersonalConstraint.end_date >= today,
            )
        )
        .scalars()
        .all()
    )
    return [(r.start_date, r.end_date) for r in rows]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/constraints.py
git commit -m "feat: add constraints service with submit/approve/reject/cancel/cap"
```

---

### Task 4: Routes

**Files:**
- Create: `backend/app/routes/constraints.py`

- [ ] **Step 1: Write the routes**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, PersonalConstraint, Soldier
from app.db.session import get_session
from app.services import constraints as svc

router = APIRouter(tags=["constraints"])


# ── Schemas ──────────────────────────────────────────────

class ConstraintOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str
    status: str
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime


class SubmitRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(max_length=1000)


class ApproveRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    decision_note: str = Field(max_length=1000)


class PendingCountOut(BaseModel):
    count: int


# ── Helpers ──────────────────────────────────────────────

def _out(c: PersonalConstraint) -> ConstraintOut:
    return ConstraintOut(
        id=c.id,
        soldier_id=c.soldier_id,
        start_date=c.start_date,
        end_date=c.end_date,
        reason=c.reason,
        status=c.status,
        decided_by=c.decided_by,
        decided_at=c.decided_at,
        decision_note=c.decision_note,
        created_at=c.created_at,
    )


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


# ── Self-service endpoints (under /me handled by route prefix in main.py) ──

@router.get("/me/constraints", response_model=list[ConstraintOut])
def list_own(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    return [_out(c) for c in svc.list_constraints(session, soldier_id=user.id)]


@router.post("/me/constraints", response_model=ConstraintOut, status_code=status.HTTP_201_CREATED)
def submit(
    body: SubmitRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut:
    try:
        c = svc.submit_constraint(
            session,
            soldier_id=user.id,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            actor_id=user.id,
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    return _out(c)


@router.delete("/me/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(
    constraint_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None or c.soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.cancel_constraint(session, constraint_id=constraint_id, actor_id=user.id)
    session.commit()


# ── Cross-soldier view ──

@router.get("/soldiers/{soldier_id}/constraints", response_model=list[ConstraintOut])
def list_for_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.CONSTRAINT_READ, target_node=_node_of(session, s))
    return [_out(c) for c in svc.list_constraints(session, soldier_id=soldier_id)]


# ── Approval management ──

@router.get("/constraints/pending", response_model=list[ConstraintOut])
def pending_list(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    roots = scope_root_ids(session, user)
    authorize(session, user, Action.CONSTRAINT_READ, target_node=None)
    if user.role == "admin":
        from app.db.models import PersonalConstraint

        rows = list(
            session.execute(
                select(PersonalConstraint)
                .where(PersonalConstraint.status == "pending")
                .order_by(PersonalConstraint.created_at.asc())
            )
            .scalars()
            .all()
        )
        return [_out(c) for c in rows]
    return [_out(c) for c in svc.list_pending_approvals(session, node_ids=roots)]


@router.get("/constraints/pending/count", response_model=PendingCountOut)
def pending_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PendingCountOut:
    roots = scope_root_ids(session, user)
    authorize(session, user, Action.CONSTRAINT_READ, target_node=None)
    if not roots and user.role != "admin":
        return PendingCountOut(count=0)
    if user.role == "admin":
        from app.db.models import PersonalConstraint

        cnt = (
            session.execute(
                select(PersonalConstraint).where(PersonalConstraint.status == "pending")
            )
            .scalars()
            .count()
        )
        return PendingCountOut(count=cnt)
    return PendingCountOut(count=svc.pending_approval_count(session, node_ids=roots))


@router.post("/constraints/{constraint_id}/approve", response_model=ConstraintOut)
def approve(
    constraint_id: uuid.UUID,
    body: ApproveRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = _load_soldier(session, c.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=_node_of(session, s))
    try:
        c = svc.approve_constraint(
            session, constraint_id=constraint_id, actor_id=user.id, decision_note=body.decision_note
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    return _out(c)


@router.post("/constraints/{constraint_id}/reject", response_model=ConstraintOut)
def reject(
    constraint_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = _load_soldier(session, c.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=_node_of(session, s))
    try:
        c = svc.reject_constraint(
            session, constraint_id=constraint_id, actor_id=user.id, decision_note=body.decision_note
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    return _out(c)
```

Wait, I'm importing `select` and `PersonalConstraint` inside the functions to avoid circular imports or because I forgot to import at the top. Let me fix the routes to have proper imports.

Actually, in `pending_list` and `pending_count`, I'm importing `select` and `PersonalConstraint` inside the admin branch. This is because the route file doesn't import those at the top. Let me clean this up.

- [ ] **Step 2: Commit**

```bash
git add backend/app/routes/constraints.py
git commit -m "feat: add constraint routes for self-service and approval"
```

---

### Task 5: Wire up routes in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add import and router registration**

Add import after existing route imports:
```python
from app.routes import constraints as constraint_routes
```

Add `app.include_router` after existing ones:
```python
    app.include_router(constraint_routes.router, prefix="/api")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register constraint routes"
```

---

### Task 6: Frontend API client

**Files:**
- Create: `frontend/src/api/constraints.ts`

- [ ] **Step 1: Write the API client**

```typescript
import { api } from "./client";

export interface PersonalConstraint {
  id: string;
  soldier_id: string;
  start_date: string;
  end_date: string;
  reason: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export async function listMyConstraints(): Promise<PersonalConstraint[]> {
  return (await api.get<PersonalConstraint[]>("/me/constraints")).data;
}

export async function submitConstraint(input: {
  start_date: string;
  end_date: string;
  reason: string;
}): Promise<PersonalConstraint> {
  return (await api.post<PersonalConstraint>("/me/constraints", input)).data;
}

export async function cancelConstraint(id: string): Promise<void> {
  await api.delete(`/me/constraints/${id}`);
}

export async function listPendingApprovals(): Promise<PersonalConstraint[]> {
  return (await api.get<PersonalConstraint[]>("/constraints/pending")).data;
}

export async function getPendingCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/constraints/pending/count");
  return r.data.count;
}

export async function approveConstraint(
  id: string,
  note?: string
): Promise<PersonalConstraint> {
  return (
    await api.post<PersonalConstraint>(`/constraints/${id}/approve`, {
      decision_note: note || null,
    })
  ).data;
}

export async function rejectConstraint(
  id: string,
  note: string
): Promise<PersonalConstraint> {
  return (
    await api.post<PersonalConstraint>(`/constraints/${id}/reject`, {
      decision_note: note,
    })
  ).data;
}

export async function listSoldierConstraints(
  soldierId: string
): Promise<PersonalConstraint[]> {
  return (await api.get<PersonalConstraint[]>(`/soldiers/${soldierId}/constraints`)).data;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/constraints.ts
git commit -m "feat: add frontend constraint API client"
```

---

### Task 7: MyRequestsPage + ApprovalsPage

**Files:**
- Create: `frontend/src/pages/MyRequestsPage.tsx`
- Create: `frontend/src/pages/ApprovalsPage.tsx`

- [ ] **Step 1: Write MyRequestsPage**

```tsx
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { listExemptions, Exemption } from "../api/exemptions";
import {
  PersonalConstraint,
  cancelConstraint,
  listMyConstraints,
  submitConstraint,
} from "../api/constraints";

export default function MyRequestsPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [exemptions, setExemptions] = useState<Exemption[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");

  const refresh = useCallback(async () => {
    setItems(await listMyConstraints());
    setExemptions(await listExemptions("me"));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await submitConstraint({
      start_date: start,
      end_date: end,
      reason,
    });
    setStart(""); setEnd(""); setReason("");
    await refresh();
  }

  async function onCancel(id: string) {
    if (!confirm(t("my_requests.cancel") + "?")) return;
    await cancelConstraint(id);
    await refresh();
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "text-amber-600",
      approved: "text-green-600",
      rejected: "text-red-600",
    };
    return <span className={colors[status] ?? ""}>{t(`my_requests.${status}`)}</span>;
  };

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6">
        <h2 className="text-xl font-semibold">{t("my_requests.title")}</h2>

        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 border-b pb-4">
          <input type="date" className="border rounded p-1" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="req-start" />
          <input type="date" className="border rounded p-1" value={end} onChange={(e) => setEnd(e.target.value)} required data-testid="req-end" />
          <input className="border rounded p-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("my_requests.reason")} required data-testid="req-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="req-submit">{t("my_requests.send")}</button>
        </form>

        {items.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.none")}</p>}

        <ul className="text-sm space-y-2" data-testid="constraints-list">
          {items.map((c) => (
            <li key={c.id} className="flex items-center gap-3" data-testid={`constraint-row-${c.id}`}>
              <span>{c.start_date} → {c.end_date}</span>
              <span className="text-gray-500">{c.reason}</span>
              {statusBadge(c.status)}
              {c.status === "pending" && (
                <button className="text-rejected text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                  {t("my_requests.cancel")}
                </button>
              )}
            </li>
          ))}
        </ul>

        <div className="pt-4 border-t">
          <h3 className="font-medium">{t("my_requests.my_exemptions")}</h3>
          {exemptions.length === 0 && <p className="text-sm text-gray-500">{t("exemptions.none")}</p>}
          <ul className="text-sm space-y-1">
            {exemptions.map((ex) => (
              <li key={ex.id}>{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</li>
            ))}
          </ul>
        </div>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 2: Write ApprovalsPage**

```tsx
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import {
  PersonalConstraint,
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setItems(await listPendingApprovals());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onApprove(id: string) {
    await approveConstraint(id);
    await refresh();
  }

  async function onReject(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    await rejectConstraint(id, note);
    const next = { ...rejectNotes };
    delete next[id];
    setRejectNotes(next);
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("approvals.title")}</h2>

        {items.length === 0 && <p className="text-sm text-gray-500">{t("approvals.none")}</p>}

        <ul className="space-y-3" data-testid="approvals-list">
          {items.map((c) => (
            <li key={c.id} className="border rounded p-3 flex items-center gap-4" data-testid={`approval-row-${c.id}`}>
              <div className="flex-1">
                <p className="text-sm"><strong>{c.soldier_id}</strong> — {c.start_date} → {c.end_date}</p>
                <p className="text-xs text-gray-500">{c.reason}</p>
              </div>
              <div className="flex items-center gap-2">
                <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onApprove(c.id)} data-testid={`approve-${c.id}`}>
                  {t("approvals.approve")}
                </button>
                <input
                  className="border rounded p-1 text-sm w-28"
                  value={rejectNotes[c.id] ?? ""}
                  onChange={(e) => setRejectNotes((prev) => ({ ...prev, [c.id]: e.target.value }))}
                  placeholder={t("approvals.decision_note")}
                  data-testid={`reject-note-${c.id}`}
                />
                <button
                  className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                  disabled={!rejectNotes[c.id]}
                  onClick={() => onReject(c.id)}
                  data-testid={`reject-${c.id}`}
                >
                  {t("approvals.reject")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat: add MyRequestsPage and ApprovalsPage"
```

---

### Task 8: Layout sidebar with badge + App.tsx routes

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update Layout.tsx — add nav links + pending count badge**

```tsx
import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const role = user?.role;
  const canManageTeam = role === "duty_manager" || role === "admin" || role === "commander";
  const canManageDuties = role === "duty_manager" || role === "admin";
  const canApprove = role === "duty_manager" || role === "admin" || role === "commander";
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (canApprove) {
      getPendingCount().then(setPendingCount).catch(() => {});
    }
  }, [canApprove]);

  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-white border-l shadow-sm p-4 space-y-2" data-testid="sidebar">
        <Link to="/" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-home">{t("nav.home")}</Link>
        <Link to="/my-duties" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-my-duties">{t("nav.my_duties")}</Link>
        <Link to="/my-requests" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-my-requests">{t("nav.my_requests")}</Link>
        <Link to="/transparency" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-transparency">{t("nav.transparency")}</Link>
        {canManageTeam && (
          <Link to="/team" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-team">{t("nav.team_hierarchy")}</Link>
        )}
        {canManageTeam && (
          <Link to="/unit-calendar" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-unit-calendar">{t("nav.unit_calendar")}</Link>
        )}
        {canApprove && (
          <Link to="/approvals" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-approvals">
            {t("nav.approvals")}
            {pendingCount > 0 && (
              <span className="ml-2 bg-red-500 text-white text-xs rounded-full px-2 py-0.5" data-testid="pending-badge">
                {pendingCount}
              </span>
            )}
          </Link>
        )}
        {canManageDuties && (
          <Link to="/duty-config" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-config">{t("nav.duty_config")}</Link>
        )}
        {canManageDuties && (
          <Link to="/duty-management" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-management">{t("nav.duty_management")}</Link>
        )}
        <Link to="/profile" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-profile">{t("nav.profile")}</Link>
      </aside>
      <div className="flex-1 flex flex-col">
        <header className="bg-white shadow-sm border-b">
          <div className="px-4 py-3 flex items-center justify-between">
            <h1 className="text-lg font-bold">{t("app.title")}</h1>
            <button onClick={() => logout()} className="text-sm text-indigo-600 hover:text-indigo-800" data-testid="logout-button">
              {t("home.logout")}
            </button>
          </div>
        </header>
        <main className="flex-1 px-4 py-6">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update App.tsx — add routes**

Add imports:
```tsx
import ApprovalsPage from "./pages/ApprovalsPage";
import MyRequestsPage from "./pages/MyRequestsPage";
```

Add routes after existing ones:
```tsx
<Route path="/my-requests" element={<ForcedPasswordGate><MyRequestsPage /></ForcedPasswordGate>} />
<Route path="/approvals" element={<ForcedPasswordGate><ApprovalsPage /></ForcedPasswordGate>} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Layout.tsx frontend/src/App.tsx
git commit -m "feat: add constraint nav links, pending badge, and routes"
```

---

### Task 9: i18n strings

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add my_requests and approvals sections, update nav**

Add before `"duty_config"`:
```json
  "my_requests": {
    "title": "הבקשות והפטורים שלי",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "reason": "סיבה",
    "send": "שלח בקשה",
    "pending": "ממתין לאישור",
    "approved": "אושר",
    "rejected": "נדחה",
    "cancel": "בטל בקשה",
    "none": "אין בקשות",
    "my_exemptions": "הפטורים שלי"
  },
  "approvals": {
    "title": "אישור בקשות",
    "none": "אין בקשות ממתינות לאישור",
    "approve": "אשר",
    "reject": "דחה",
    "decision_note": "הערה"
  },
```

Add nav entries inside `"nav"`:
```json
    "my_requests": "הבקשות שלי",
    "approvals": "אישור בקשות",
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: add i18n for constraints and approvals"
```

---

### Task 10: Unit tests

**Files:**
- Create: `backend/tests/unit/test_constraints_service.py`

- [ ] **Step 1: Write and run unit tests**

```python
import uuid
from datetime import date, timedelta

import pytest

from app.db.models import PersonalConstraint
from app.services.constraints import (
    ConstraintError,
    approve_constraint,
    cancel_constraint,
    get_approved_constraint_dates,
    list_constraints,
    reject_constraint,
    submit_constraint,
)
from tests.helpers import create_soldier


def test_submit_success(admin_session):
    s = create_soldier(admin_session, personal_number="7400001")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.commit()
    assert c.status == "pending"
    assert c.soldier_id == s.id


def test_submit_auto_approve(monkeypatch, admin_session):
    from app.settings import get_settings
    monkeypatch.setattr("app.settings.Settings.get", lambda self, k, d=None: False if k == "constraints.require_manager_approval" else d)
    s = create_soldier(admin_session, personal_number="7400002")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=s.id,
    )
    admin_session.commit()
    assert c.status == "approved"


def test_submit_cap_enforced(admin_session):
    s = create_soldier(admin_session, personal_number="7400003")
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=15),
        reason="ארוך",
        actor_id=None,
    )
    admin_session.flush()
    with pytest.raises(ConstraintError, match="cap_exceeded"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date.today() + timedelta(days=20),
            end_date=date.today() + timedelta(days=21),
            reason="עוד",
            actor_id=None,
        )


def test_submit_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="7400004")
    with pytest.raises(ConstraintError, match="bad_date_range"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 5),
            reason="no",
            actor_id=None,
        )


def test_submit_past_start(admin_session):
    s = create_soldier(admin_session, personal_number="7400005")
    with pytest.raises(ConstraintError, match="start_date_in_past"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 5),
            reason="past",
            actor_id=None,
        )


def test_submit_unknown_soldier(admin_session):
    with pytest.raises(ConstraintError, match="soldier_not_found"):
        submit_constraint(
            admin_session,
            soldier_id=uuid.uuid4(),
            start_date=date.today() + timedelta(days=1),
            end_date=date.today() + timedelta(days=5),
            reason="no",
            actor_id=None,
        )


def test_approve_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400006")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approved = approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.commit()
    assert approved.status == "approved"
    assert approved.decided_by == s.id


def test_approve_not_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400007")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_reject(admin_session):
    s = create_soldier(admin_session, personal_number="7400008")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    rejected = reject_constraint(admin_session, constraint_id=c.id, actor_id=s.id, decision_note="לא מתאים")
    admin_session.commit()
    assert rejected.status == "rejected"
    assert rejected.decision_note == "לא מתאים"


def test_cancel_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400009")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None


def test_cancel_not_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400010")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        cancel_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_list_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="7400011")
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
        reason="א",
        actor_id=None,
    )
    admin_session.flush()
    assert len(list_constraints(admin_session, soldier_id=s.id)) == 1


def test_get_approved_dates(admin_session):
    s = create_soldier(admin_session, personal_number="7400012")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=10),
        end_date=date.today() + timedelta(days=15),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    dates = get_approved_constraint_dates(admin_session, soldier_id=s.id)
    assert len(dates) == 1
    assert dates[0][0] == date.today() + timedelta(days=10)


def test_constraint_not_found(admin_session):
    with pytest.raises(ConstraintError, match="constraint_not_found"):
        approve_constraint(admin_session, constraint_id=uuid.uuid4(), actor_id=None)
```

- [ ] **Step 2: Run unit tests**

```bash
cd backend && python -m pytest tests/unit/test_constraints_service.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_constraints_service.py
git commit -m "test: add unit tests for constraints service"
```

---

### Task 11: Integration tests

**Files:**
- Create: `backend/tests/integration/test_constraints_api.py`

- [ ] **Step 1: Write and run integration tests**

```python
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_soldier_submit_and_list(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500001")
    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    )
    assert r.status_code == 201, r.text
    r2 = client.get("/api/me/constraints", headers=auth_headers(s))
    assert len(r2.json()) == 1


def test_soldier_cancel_own(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500002")
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.delete(f"/api/me/constraints/{c['id']}", headers=auth_headers(s))
    assert r.status_code == 204
    r2 = client.get("/api/me/constraints", headers=auth_headers(s))
    assert len(r2.json()) == 0


def test_commander_approves_in_subtree(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7500003", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500004", hierarchy_node_id=b.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


def test_commander_out_of_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="7500005", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500006", hierarchy_node_id=other.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r.status_code == 403


def test_soldier_cannot_approve(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500007", role="soldier")
    target = create_soldier(admin_session, personal_number="7500008")
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(s), json={})
    assert r.status_code == 403


def test_pending_count(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    dm = create_soldier(admin_session, personal_number="7500009", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="7500010", hierarchy_node_id=d.id)
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.get("/api/constraints/pending/count", headers=auth_headers(dm))
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_reject_requires_note(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    cmd = create_soldier(admin_session, personal_number="7500011", role="commander")
    d.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500012", hierarchy_node_id=d.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(
        f"/api/constraints/{c['id']}/reject",
        headers=auth_headers(cmd),
        json={"decision_note": "לא מתאים"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
```

- [ ] **Step 2: Run integration tests**

```bash
cd backend && python -m pytest tests/integration/test_constraints_api.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_constraints_api.py
git commit -m "test: add integration tests for constraints API"
```
