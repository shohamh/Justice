# Batch 6 — Inline Audit History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix item 17 from the user-reported-issues triage (spec:
`docs/superpowers/specs/2026-08-18-user-reported-issues-triage-design.md`,
Batch 6 / DC7): a user ("שניר") cannot see who created or canceled an
exemption or constraint record, or when — the system already writes an
audit-log row for every such action, but there is no read surface for it
except one narrow internal consumer (`bug_reports` diagnostics). Add a
scoped read endpoint and a small inline "history" block on the exemption and
constraint record UIs. No new global audit-log admin page.

**Architecture:** One new backend route module
(`backend/app/routes/audit_logs.py`) exposes
`GET /api/audit-logs?entity_type=&entity_id=`. It re-uses the exact
authorization pattern already used by the exemption/constraint detail
endpoints (self-view, or `authorize()` with `Action.EXEMPTION_READ` /
`Action.CONSTRAINT_READ` against the owning soldier's hierarchy node) —
no new authorization helper, no new `system_settings` key. The audit writer
(`backend/app/audit/writer.py`) is untouched; this batch only reads
`AuditLog` rows already being written by `app/services/exemptions.py` and
`app/services/constraints.py`. On the frontend, one new reusable
`AuditHistoryBlock` component fetches and renders the entries lazily
(collapsed by default, fetched on first expand) and is embedded in the two
existing per-record UI surfaces: `ExemptionInstanceModal.tsx` (exemption
detail) and the constraint rows in `MyRequestsPage.tsx`.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript +
react-i18next + Vitest (frontend), pytest (backend tests, marker: `misc`,
per the "misc: health check, audit log, settings loader" area).

## Global Constraints

- No global audit-log admin page — this is locked by decision DC7 in the
  spec; do not add one even as a convenience.
- The audit writer (`backend/app/audit/writer.py`'s `write_audit()`) is
  unchanged — this batch is read-only. If a genuine bug is found in the
  write path, it must be flagged in this plan rather than silently fixed
  (see the "Known limitation" note under Task 1 below — a real gap was
  found in `cancel_constraint`, and it is flagged, not fixed, per this
  constraint).
- RBAC: the new endpoint must reuse the existing per-record exemption/
  constraint scope-check pattern (`authorize()` with `Action.EXEMPTION_READ`
  / `Action.CONSTRAINT_READ`, exactly as `backend/app/routes/exemptions.py`
  `get_detail()` and `backend/app/routes/constraints.py` `list_for_soldier()`
  already do), not a new ad hoc rule.
- Backend tests: `pytest -m misc -q` must stay green; run `pytest -q` (full
  fast suite) before the final commit of this plan.
- Frontend: `npm test`, `npm run lint` (zero warnings), `npm run typecheck`
  must stay green.
- `entity_type` is restricted to an allowlist (`soldier_exemption`,
  `personal_constraint` — see Task 1's design note for why those exact
  strings and not `exemption`/`constraint`) so the generic-looking query
  params cannot be used to fetch audit history for unrelated entity types
  that this endpoint's authorization logic does not know how to scope.

---

## Task 1: Backend — `GET /api/audit-logs` scoped read endpoint

**Files:**
- Create: `backend/app/routes/audit_logs.py`
- Modify: `backend/app/main.py:27` (add import), `backend/app/main.py:179`
  (add `app.include_router(...)` call, right after the exemption/constraint
  routers)
- Modify: `backend/tests/conftest.py:273` (add
  `"test_audit_logs_api": "misc",` to `_AREA_MARKERS`, in the `# misc:`
  block)
- Test: `backend/tests/integration/test_audit_logs_api.py` (new file)

**Interfaces:**
- Produces: `GET /api/audit-logs?entity_type=<str>&entity_id=<uuid>` →
  `list[AuditLogEntryOut]` where
  ```python
  class AuditLogEntryOut(BaseModel):
      id: uuid.UUID
      action: str
      actor_id: uuid.UUID | None
      actor_name: str | None
      entity_type: str
      entity_id: uuid.UUID | None
      before: dict[str, Any] | None
      after: dict[str, Any] | None
      context: dict[str, Any] | None
      created_at: datetime
  ```
  Ordered newest-first (`created_at` descending).
- Consumes (existing, unchanged): `app.db.models.AuditLog` (columns: `id`,
  `action: str`, `entity_type: str`, `actor_id: uuid.UUID | None`,
  `entity_id: uuid.UUID | None`, `before: dict | None`, `after: dict | None`,
  `context: dict | None`, `created_at: datetime`) — read via
  `sqlalchemy.select(AuditLog).where(...)`, the exact pattern already used
  by `_audit_snapshot` in `backend/app/services/bug_reports.py:47-62` and by
  `backend/app/services/duty_history.py:297,532`.
- Consumes (existing, unchanged): `app.auth.authz.authorize(session, user,
  action: str, *, target_node: HierarchyNode | None) -> None` (raises 403),
  `app.auth.authz.Action.EXEMPTION_READ = "exemption.read"`,
  `app.auth.authz.Action.CONSTRAINT_READ = "constraint.read"`.
- Consumes (existing, unchanged): `app.db.models.SoldierExemption` (columns
  used: `id`, `soldier_id`), `app.db.models.PersonalConstraint` (columns
  used: `id`, `soldier_id`), `app.db.models.Soldier` (columns used: `id`,
  `full_name`, `hierarchy_node_id`), `app.db.models.HierarchyNode`.
- Consumes (existing, unchanged): `app.auth.deps.require_password_changed`
  (FastAPI dependency returning the authenticated `Soldier`, already
  imported this way in `backend/app/routes/exemptions.py:11` and
  `backend/app/routes/constraints.py:12`).

**Design notes (read before implementing):**

1. **Entity-type strings.** `write_audit()` calls in
   `backend/app/services/exemptions.py:59,120,181` use
   `entity_type="soldier_exemption"`, and calls in
   `backend/app/services/constraints.py:87,157,178,237,273` use
   `entity_type="personal_constraint"`. These are the exact strings the
   allowlist must accept — not `"exemption"` / `"constraint"` (which don't
   appear anywhere as a `write_audit` `entity_type` value).

2. **Known limitation, flagged not fixed.** `cancel_constraint()` in
   `backend/app/services/constraints.py:245-278` writes its
   `"constraint.cancel"` audit row and then calls `session.delete(c)` —
   the `PersonalConstraint` row is hard-deleted in the same transaction.
   This means that after a soldier cancels a constraint, there is no
   longer a live `PersonalConstraint` row to resolve `entity_id` back to a
   `soldier_id` for the authorization check via a simple `session.get()`.
   Per this plan's Global Constraints, the write path
   (`cancel_constraint`'s hard delete) is NOT changed here — instead, the
   read endpoint below resolves `soldier_id` with a fallback: try loading
   the live entity row first, and if that comes back `None`, fall back to
   scanning the entity's own audit rows for a `before`/`after` snapshot
   that contains a `"soldier_id"` key (present on `constraint.submit`'s
   `after` and on both exemption-grant actions' `after`). This makes the
   very case the user reported — "who canceled this constraint" — work
   correctly: the constraint row is gone, but its audit trail (including
   the cancellation) is still resolvable and readable by the same people
   who could see the constraint while it existed. If a constraint is
   canceled before ever being submitted with a `soldier_id`-bearing audit
   row (impossible under current code — `constraint.submit` always fires
   first and always includes `soldier_id`), the endpoint would 404; this
   is not reachable via any current code path so it is not tested
   separately.

   A second, smaller consequence of the hard-delete is a UI-level gap
   documented (not fixed) in Task 3: once a constraint is canceled, the
   `MyRequestsPage.tsx` row for it disappears entirely (it's gone from
   every status bucket), so there's no row left to attach a "show history"
   toggle to — a user can see cancellation history for an exemption
   (revoke keeps the row, just marks it revoked) but not, from that page,
   for an already-canceled constraint. The backend endpoint itself does
   not have this limitation; only the current frontend surfaces do,
   because they render lists of live rows. This is flagged as an
   out-of-scope UI limitation, matching the instruction to flag rather
   than silently expand scope by changing `cancel_constraint`'s delete
   behavior (a data-retention decision, not part of DC7).

3. **Authorization mirrors the existing detail-view checks exactly.** For
   `entity_type="soldier_exemption"`: same as
   `backend/app/routes/exemptions.py` `get_detail()` (`s.id != user.id` →
   `authorize(session, user, Action.EXEMPTION_READ, target_node=node)`).
   For `entity_type="personal_constraint"`: same as
   `backend/app/routes/constraints.py` `list_for_soldier()` (`s.id !=
   user.id` → `authorize(session, user, Action.CONSTRAINT_READ,
   target_node=node)`).

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_audit_logs_api.py`:

```python
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType, PersonalConstraint
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name):
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_rejects_unsupported_entity_type(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8100001")
    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier", "entity_id": str(s.id)},
        headers=auth_headers(s),
    )
    assert r.status_code == 400, r.text


def test_soldier_sees_own_exemption_history(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8100002")
    et = _et(admin_session, "פטור-ה1")
    grant = client.post(
        f"/api/soldiers/{s.id}/exemptions",
        headers=auth_headers(s),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "רפואי"},
    )
    assert grant.status_code == 201, grant.text
    exemption_id = grant.json()["id"]

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": exemption_id},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["action"] == "exemption.grant"
    assert entries[0]["actor_name"] == s.full_name
    assert entries[0]["entity_type"] == "soldier_exemption"
    assert entries[0]["created_at"]


def test_commander_in_subtree_sees_exemption_history(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-audit1")
    b = create_node(admin_session, level="branch", name="b-audit1", parent=d)
    cmd = create_soldier(admin_session, personal_number="8100003", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="8100004", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-ה2")
    grant = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    assert grant.status_code == 201, grant.text
    exemption_id = grant.json()["id"]

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": exemption_id},
        headers=auth_headers(cmd),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["action"] == "exemption.grant"


def test_commander_outside_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-audit2")
    b = create_node(admin_session, level="branch", name="b-audit2", parent=d)
    other = create_node(admin_session, level="department", name="other-audit2")
    cmd = create_soldier(admin_session, personal_number="8100005", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="8100006", hierarchy_node_id=other.id)
    et = _et(admin_session, "פטור-ה3")

    # Grant directly through the service layer (rather than the HTTP POST
    # endpoint) since no in-scope actor for `other` exists in this test —
    # the point of this test is read-side scoping, not the grant path.
    from app.services import exemptions as exemptions_svc

    ex = exemptions_svc.grant_exemption(
        admin_session, soldier_id=target.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None, reason=None, actor_id=target.id,
    )
    admin_session.commit()

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": str(ex.id)},
        headers=auth_headers(cmd),
    )
    assert r.status_code == 403, r.text


def test_soldier_sees_own_constraint_history(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8100007")
    submit = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    )
    assert submit.status_code == 201, submit.text
    constraint_id = submit.json()["id"]

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "personal_constraint", "entity_id": constraint_id},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["action"] == "constraint.submit"


def test_history_survives_constraint_hard_delete_on_cancel(client: TestClient, admin_session: Session):
    """Regression test for the exact gap item 17 reports: after a constraint
    is canceled, its PersonalConstraint row is hard-deleted (see
    cancel_constraint in backend/app/services/constraints.py), but the audit
    trail — including the cancellation itself — must still be readable."""
    s = create_soldier(admin_session, personal_number="8100008")
    submit = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    )
    assert submit.status_code == 201, submit.text
    constraint_id = submit.json()["id"]

    cancel = client.delete(f"/api/me/constraints/{constraint_id}", headers=auth_headers(s))
    assert cancel.status_code == 204, cancel.text

    # The row is really gone.
    assert admin_session.get(PersonalConstraint, constraint_id) is None

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "personal_constraint", "entity_id": constraint_id},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    actions = {e["action"] for e in r.json()}
    assert actions == {"constraint.submit", "constraint.cancel"}


def test_not_found_for_unknown_entity_id(client: TestClient, admin_session: Session):
    import uuid

    s = create_soldier(admin_session, personal_number="8100009")
    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": str(uuid.uuid4())},
        headers=auth_headers(s),
    )
    assert r.status_code == 404, r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_audit_logs_api.py -v`
Expected: FAIL — `404 Not Found` for every request (route
`/api/audit-logs` doesn't exist yet), or a collection error if the test
file itself can't import (it can — all imports used already exist).

- [ ] **Step 3: Implement the route module**

Create `backend/app/routes/audit_logs.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import AuditLog, HierarchyNode, PersonalConstraint, Soldier, SoldierExemption
from app.db.session import get_session

router = APIRouter(tags=["audit-logs"])

# Exact entity_type strings written by write_audit() calls in
# app/services/exemptions.py and app/services/constraints.py. This is
# deliberately an allowlist, not a passthrough: the query params look
# generic, but this endpoint only knows how to authorize these two entity
# kinds (by resolving them back to an owning soldier and re-using that
# soldier's exemption/constraint read authorization). Accepting arbitrary
# entity_type values here would silently expose other entities' audit
# history without the matching per-type authorization check.
_ALLOWED_ENTITY_TYPES = {"soldier_exemption", "personal_constraint"}


class AuditLogEntryOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    context: dict[str, Any] | None
    created_at: datetime


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _resolve_soldier_id(
    session: Session, entity_type: str, entity_id: uuid.UUID, audit_rows: list[AuditLog]
) -> uuid.UUID | None:
    """Resolve the soldier who owns this exemption/constraint record.

    Tries the live row first. Falls back to scanning the entity's own audit
    trail for a soldier_id in an earlier before/after snapshot, because
    cancel_constraint() hard-deletes the PersonalConstraint row after
    writing its audit entries (see backend/app/services/constraints.py:278)
    — without this fallback, a canceled constraint's history would be
    unreachable, which is the exact gap item 17 reports.
    """
    if entity_type == "soldier_exemption":
        row = session.get(SoldierExemption, entity_id)
        if row is not None:
            return row.soldier_id
    elif entity_type == "personal_constraint":
        row = session.get(PersonalConstraint, entity_id)
        if row is not None:
            return row.soldier_id
    for entry in audit_rows:
        for snapshot in (entry.after, entry.before):
            raw = snapshot.get("soldier_id") if snapshot else None
            if raw:
                try:
                    return uuid.UUID(str(raw))
                except ValueError:
                    continue
    return None


@router.get("/audit-logs", response_model=list[AuditLogEntryOut])
def list_audit_logs(
    entity_type: str = Query(...),
    entity_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AuditLogEntryOut]:
    if entity_type not in _ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_entity_type")

    rows = list(
        session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.desc())
        )
        .scalars()
        .all()
    )

    soldier_id = _resolve_soldier_id(session, entity_type, entity_id, rows)
    if soldier_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    if s.id != user.id:
        action = Action.EXEMPTION_READ if entity_type == "soldier_exemption" else Action.CONSTRAINT_READ
        authorize(session, user, action, target_node=_node_of(session, s))

    actor_ids = {r.actor_id for r in rows if r.actor_id is not None}
    actor_names = (
        {
            a.id: a.full_name
            for a in session.execute(select(Soldier).where(Soldier.id.in_(actor_ids))).scalars().all()
        }
        if actor_ids
        else {}
    )
    return [
        AuditLogEntryOut(
            id=r.id,
            action=r.action,
            actor_id=r.actor_id,
            actor_name=actor_names.get(r.actor_id) if r.actor_id is not None else None,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            before=r.before,
            after=r.after,
            context=r.context,
            created_at=r.created_at,
        )
        for r in rows
    ]
```

Wire it into the app in `backend/app/main.py`. Add the import after line 26
(`from app.routes import constraints as constraint_routes`):

```python
from app.routes import audit_logs as audit_log_routes
```

(keep the existing alphabetization loose — this file already isn't
strictly alphabetized; just group it near `constraint_routes`/
`exemption_routes` for discoverability). Add the registration after the
`exemption_request_routes` line (originally `main.py:180`):

```python
    app.include_router(audit_log_routes.router, prefix="/api")
```

- [ ] **Step 4: Register the pytest area marker**

In `backend/tests/conftest.py`, inside the `# misc:` block of
`_AREA_MARKERS` (right after `"test_bug_reports_api": "misc",`, originally
around line 273), add:

```python
    "test_audit_logs_api": "misc",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_audit_logs_api.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Run the full misc marker slice**

Run: `cd backend && .venv/Scripts/pytest -m misc -q`
Expected: PASS, no regressions in the existing `misc`-marked suite
(health check, audit-log append tests, settings loader, bug reports).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/audit_logs.py backend/app/main.py backend/tests/conftest.py backend/tests/integration/test_audit_logs_api.py
git commit -m "feat: add scoped GET /audit-logs read endpoint for exemption/constraint history"
```

---

## Task 2: Frontend — API wrapper + reusable `AuditHistoryBlock` component

**Files:**
- Create: `frontend/src/api/auditLogs.ts`
- Create: `frontend/src/components/AuditHistoryBlock.tsx`
- Modify: `frontend/src/i18n/he.json` (add an `audit_history` section)
- Test: `frontend/src/components/AuditHistoryBlock.test.tsx`

**Interfaces:**
- Produces (API wrapper):
  ```typescript
  export type AuditLogEntityType = "soldier_exemption" | "personal_constraint";

  export interface AuditLogEntry {
    id: string;
    action: string;
    actor_id: string | null;
    actor_name: string | null;
    entity_type: string;
    entity_id: string | null;
    before: Record<string, unknown> | null;
    after: Record<string, unknown> | null;
    context: Record<string, unknown> | null;
    created_at: string;
  }

  export async function listAuditLogs(
    entityType: AuditLogEntityType,
    entityId: string,
  ): Promise<AuditLogEntry[]>;
  ```
- Produces (component):
  ```typescript
  export default function AuditHistoryBlock(props: {
    entityType: AuditLogEntityType;
    entityId: string;
  }): JSX.Element
  ```
  Renders a collapsed-by-default toggle (`data-testid="audit-history-toggle-{entityId}"`);
  expanding it lazily fetches via `listAuditLogs` and renders a list
  (`data-testid="audit-history-list-{entityId}"`) of entries
  (`data-testid="audit-history-entry-{id}"`), each showing a translated
  action label, the actor's name (or "מערכת" if `actor_id` is null — the
  audit writer allows a null actor for system-initiated writes, per
  `write_audit`'s `actor_id: uuid.UUID | None` signature), and the
  timestamp.
- Consumes (existing): `frontend/src/api/client.ts`'s `api` (axios
  instance) — same `api.get<T>(url, { params })` pattern used by
  `frontend/src/api/assignments.ts:37`.

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/components/AuditHistoryBlock.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import AuditHistoryBlock from "./AuditHistoryBlock";
import * as auditLogsApi from "../api/auditLogs";

describe("AuditHistoryBlock", () => {
  it("is collapsed by default and does not fetch until expanded", () => {
    const spy = vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([]);
    render(<AuditHistoryBlock entityType="soldier_exemption" entityId="ex-1" />);
    expect(screen.queryByTestId("audit-history-list-ex-1")).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches and renders entries on expand", async () => {
    vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([
      {
        id: "log-1", action: "exemption.grant", actor_id: "u-1", actor_name: "יוסי כהן",
        entity_type: "soldier_exemption", entity_id: "ex-1",
        before: null, after: { soldier_id: "s-1" }, context: null,
        created_at: "2026-01-01T10:00:00Z",
      },
    ]);
    render(<AuditHistoryBlock entityType="soldier_exemption" entityId="ex-1" />);
    fireEvent.click(screen.getByTestId("audit-history-toggle-ex-1"));
    await waitFor(() => expect(screen.getByTestId("audit-history-entry-log-1")).toBeInTheDocument());
    expect(screen.getByText(/יוסי כהן/)).toBeInTheDocument();
  });

  it("shows a fallback actor label when actor_id is null", async () => {
    vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([
      {
        id: "log-2", action: "constraint.cancel", actor_id: null, actor_name: null,
        entity_type: "personal_constraint", entity_id: "c-1",
        before: { status: "pending_commander" }, after: { deleted: true }, context: null,
        created_at: "2026-01-02T10:00:00Z",
      },
    ]);
    render(<AuditHistoryBlock entityType="personal_constraint" entityId="c-1" />);
    fireEvent.click(screen.getByTestId("audit-history-toggle-c-1"));
    await waitFor(() => expect(screen.getByTestId("audit-history-entry-log-2")).toBeInTheDocument());
    expect(screen.getByText(/מערכת/)).toBeInTheDocument();
  });

  it("shows an empty-state message when there is no history", async () => {
    vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([]);
    render(<AuditHistoryBlock entityType="soldier_exemption" entityId="ex-2" />);
    fireEvent.click(screen.getByTestId("audit-history-toggle-ex-2"));
    await waitFor(() => expect(screen.getByTestId("audit-history-list-ex-2")).toBeInTheDocument());
    expect(screen.getByText("אין היסטוריה")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- AuditHistoryBlock`
Expected: FAIL — `Cannot find module './AuditHistoryBlock'` (and
`../api/auditLogs` doesn't exist yet either).

- [ ] **Step 3: Write the API wrapper**

Create `frontend/src/api/auditLogs.ts`:

```typescript
import { api } from "./client";

export type AuditLogEntityType = "soldier_exemption" | "personal_constraint";

export interface AuditLogEntry {
  id: string;
  action: string;
  actor_id: string | null;
  actor_name: string | null;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  context: Record<string, unknown> | null;
  created_at: string;
}

export async function listAuditLogs(
  entityType: AuditLogEntityType,
  entityId: string,
): Promise<AuditLogEntry[]> {
  return (
    await api.get<AuditLogEntry[]>("/audit-logs", {
      params: { entity_type: entityType, entity_id: entityId },
    })
  ).data;
}
```

- [ ] **Step 4: Add the `audit_history` i18n section**

In `frontend/src/i18n/he.json`, insert a new top-level section right after
the closing `}` of the `"exemptions"` block (originally ending at line
237, right before `"team": {`):

```json
  "audit_history": {
    "show": "הצג היסטוריה",
    "hide": "הסתר היסטוריה",
    "none": "אין היסטוריה",
    "system": "מערכת",
    "action_exemption.grant": "פטור הוענק",
    "action_exemption.grant_commander": "פטור מפקד הוענק",
    "action_exemption.revoke": "פטור בוטל",
    "action_constraint.submit": "בקשת אילוץ הוגשה",
    "action_constraint.approve_commander_step": "אושר על ידי מפקד",
    "action_constraint.approve_duty_manager_step": "אושר סופית",
    "action_constraint.reject": "נדחה",
    "action_constraint.cancel": "אילוץ בוטל"
  },
```

(Keep the file valid JSON — this adds one sibling key to the root object,
same nesting level as `"exemptions"` and `"team"`.)

- [ ] **Step 5: Implement the component**

Create `frontend/src/components/AuditHistoryBlock.tsx`:

```tsx
import { MouseEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { AuditLogEntityType, AuditLogEntry, listAuditLogs } from "../api/auditLogs";

interface Props {
  entityType: AuditLogEntityType;
  entityId: string;
}

export default function AuditHistoryBlock({ entityType, entityId }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState(false);

  async function toggle(e: MouseEvent) {
    e.stopPropagation();
    const next = !expanded;
    setExpanded(next);
    if (next && !loaded) {
      try {
        const data = await listAuditLogs(entityType, entityId);
        setEntries(data);
        setLoaded(true);
      } catch {
        setError(true);
        setLoaded(true);
      }
    }
  }

  return (
    <div className="mt-2 text-xs" data-testid={`audit-history-${entityId}`}>
      <button
        type="button"
        onClick={(e) => void toggle(e)}
        className="text-indigo-600 dark:text-indigo-300 underline"
        data-testid={`audit-history-toggle-${entityId}`}
      >
        {expanded ? t("audit_history.hide") : t("audit_history.show")}
      </button>
      {expanded && (
        <div
          className="mt-1 space-y-1 border-t dark:border-gray-600 pt-1"
          data-testid={`audit-history-list-${entityId}`}
        >
          {error && <p className="text-red-500">{t("audit_history.none")}</p>}
          {!error && loaded && entries.length === 0 && (
            <p className="text-gray-500">{t("audit_history.none")}</p>
          )}
          {!error &&
            entries.map((entry) => (
              <p
                key={entry.id}
                className="text-gray-600 dark:text-gray-300"
                data-testid={`audit-history-entry-${entry.id}`}
              >
                {t(`audit_history.action_${entry.action}`, { defaultValue: entry.action })}
                {" — "}
                {entry.actor_name ?? t("audit_history.system")}
                {" · "}
                <span dir="ltr">{new Date(entry.created_at).toLocaleString("he-IL")}</span>
              </p>
            ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm test -- AuditHistoryBlock`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/auditLogs.ts frontend/src/components/AuditHistoryBlock.tsx frontend/src/components/AuditHistoryBlock.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add AuditHistoryBlock component and audit-logs API wrapper"
```

---

## Task 3: Frontend — embed the history block on exemption and constraint record UIs

**Files:**
- Modify: `frontend/src/components/ExemptionInstanceModal.tsx:52-75`
- Modify: `frontend/src/pages/MyRequestsPage.tsx:219-283` (the three
  constraint-status `<ul>` blocks: pending, approved, rejected)
- Test: `frontend/src/components/ExemptionInstanceModal.test.tsx` (extend)
- Test: `frontend/src/pages/MyRequestsPage.test.tsx` (extend — check first
  with `Glob`/`Read` for the existing mock setup pattern before adding a
  new test, since this file already mocks several API modules)

**Interfaces:**
- Consumes (from Task 2): `AuditHistoryBlock` component,
  `AuditLogEntityType = "soldier_exemption" | "personal_constraint"`.

**Design note on scope:** exemptions have two existing per-record UI
entry points that were considered — `ExemptionsPanel.tsx` (commander/DM
view of a soldier's exemptions inside `UnifiedSoldierModal`) and
`ExemptionInstanceModal.tsx` (a detail modal opened from `ExemptionsCell.tsx`,
used in table/chip views). `ExemptionInstanceModal` was chosen as the
single embed point because it already fetches full per-record detail via
`getExemptionDetail(soldierId, exemptionId)` on open — the same shape of
work (soldier-scoped, single-record) as the new endpoint needs, and it is
reachable both from a soldier's own exemption list and from commander/DM
views that render `ExemptionsCell`, covering the reported use case without
duplicating the toggle in two places. `ExemptionsPanel.tsx`'s inline
expandable rows already show reason/exempts-from on click — adding a
second nested toggle there was judged as more UI clutter than value for
this batch; it can reuse `AuditHistoryBlock` in a later pass if requested,
since the component is generic. For constraints, `MyRequestsPage.tsx` is
the only current UI surface that renders individual `PersonalConstraint`
records (`listSoldierConstraints` exists in `frontend/src/api/constraints.ts:67`
but has no current UI consumer — grepped and confirmed), so it is the only
place to embed here.

- [ ] **Step 1: Write the failing test for `ExemptionInstanceModal`**

In `frontend/src/components/ExemptionInstanceModal.test.tsx`, add this
test (the file already imports `render`, `screen`, `waitFor`, `vi`, `../i18n`,
`ExemptionInstanceModal`, and `* as exemptionsApi`):

```tsx
import * as auditLogsApi from "../api/auditLogs";

// ... inside the existing describe block, add:
it("renders an audit-history toggle for the exemption", async () => {
  vi.spyOn(exemptionsApi, "getExemptionDetail").mockResolvedValue({
    id: "ex-4", exemption_type_name: "פטור רפואי", is_global: true,
    start_date: "2026-01-01", end_date: null, reason: null, granted_by_name: null,
  });
  const auditSpy = vi.spyOn(auditLogsApi, "listAuditLogs").mockResolvedValue([]);
  render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-4" onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText("פטור רפואי")).toBeInTheDocument());
  expect(screen.getByTestId("audit-history-toggle-ex-4")).toBeInTheDocument();
  expect(auditSpy).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ExemptionInstanceModal`
Expected: FAIL — `Unable to find an element by: [data-testid="audit-history-toggle-ex-4"]`

- [ ] **Step 3: Embed `AuditHistoryBlock` in `ExemptionInstanceModal.tsx`**

In `frontend/src/components/ExemptionInstanceModal.tsx`, add the import
after line 6 (`import { useModalBackClose } from "../hooks/useModalBackClose";`):

```tsx
import AuditHistoryBlock from "./AuditHistoryBlock";
```

Then, inside the `{!forbidden && detail && ( ... )}` block, right after
the `granted_by_name` paragraph (originally lines 69-73) and before the
closing `</div>` at line 74, add:

```tsx
            <AuditHistoryBlock entityType="soldier_exemption" entityId={exemptionId} />
```

So that block now reads:

```tsx
        {!forbidden && detail && (
          <div className="space-y-2 text-sm">
            <p className="font-medium">{detail.exemption_type_name}</p>
            <span className="inline-block text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
              {detail.is_global ? t("exemptions.category_global") : t("exemptions.category_partial")}
            </span>
            <p className="text-gray-700 dark:text-gray-300 flex items-center gap-2">
              <span>{formatDate(detail.start_date)}</span>
              {" → "}
              <span>{detail.end_date ? formatDate(detail.end_date) : t("exemptions.forever")}</span>
              <DaysBadge start={detail.start_date} end={detail.end_date} />
            </p>
            {detail.reason && (
              <p>
                <span className="font-medium">{t("exemptions.reason")}:</span> {detail.reason}
              </p>
            )}
            {detail.granted_by_name && (
              <p>
                <span className="font-medium">{t("exemptions.granted_by")}:</span> {detail.granted_by_name}
              </p>
            )}
            <AuditHistoryBlock entityType="soldier_exemption" entityId={exemptionId} />
          </div>
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ExemptionInstanceModal`
Expected: PASS (4 tests — the 3 pre-existing plus the new one)

- [ ] **Step 5: Write the failing test for constraint rows**

`frontend/src/pages/MyRequestsPage.test.tsx` already mocks
`react-i18next` at module scope with `t: (key: string) => key` (so
translated strings render as their raw keys, not Hebrew text — assert on
`data-testid`, not text, for anything from `AuditHistoryBlock`). It already
mocks `../api/constraints` and `../api/exemptions` with `vi.mock(...)` +
per-test `vi.mocked(...).mockResolvedValue(...)`, and its shared
`beforeEach` seeds `constraintsApi.listMyConstraints` with a single fixture
row `constraint` (`id: "c1"`, `status: "pending"`, defined at the top of
the file). Follow the same pattern: add a `vi.mock("../api/auditLogs")`
call next to the existing `vi.mock` calls (after
`vi.mock("../api/dutyConfig");`), import the module, and seed its mock.

Add near the top of the file, with the other imports:

```tsx
import * as auditLogsApi from "../api/auditLogs";
```

Add next to the other `vi.mock` calls (after `vi.mock("../api/dutyConfig");`):

```tsx
vi.mock("../api/auditLogs");
```

Add inside the existing `beforeEach`, after
`vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);`:

```tsx
  vi.mocked(auditLogsApi.listAuditLogs).mockResolvedValue([]);
```

Add a new test, in a new `describe` block at the end of the file:

```tsx
describe("MyRequestsPage - inline audit history", () => {
  it("renders an audit-history toggle for the pending constraint row", async () => {
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(within(row).getByTestId("audit-history-toggle-c1")).toBeInTheDocument();
    expect(auditLogsApi.listAuditLogs).not.toHaveBeenCalled();
  });

  it("fetches history for that constraint on expand", async () => {
    vi.mocked(auditLogsApi.listAuditLogs).mockResolvedValue([
      {
        id: "log-9", action: "constraint.submit", actor_id: "sol-1", actor_name: "A",
        entity_type: "personal_constraint", entity_id: "c1",
        before: null, after: { soldier_id: "sol-1" }, context: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    fireEvent.click(within(row).getByTestId("audit-history-toggle-c1"));
    await waitFor(() =>
      expect(within(row).getByTestId("audit-history-entry-log-9")).toBeInTheDocument()
    );
    expect(auditLogsApi.listAuditLogs).toHaveBeenCalledWith("personal_constraint", "c1");
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npm test -- MyRequestsPage`
Expected: FAIL — the new `audit-history-toggle-*` test id is not present.

- [ ] **Step 7: Embed `AuditHistoryBlock` in the constraint rows**

In `frontend/src/pages/MyRequestsPage.tsx`, add the import near the other
component imports (after `import { DaysBadge } from "../components/DaysBadge";`):

```tsx
import AuditHistoryBlock from "../components/AuditHistoryBlock";
```

Add `<AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />`
to all three constraint `<li>` blocks. The pending block (originally lines
226-241) becomes:

```tsx
                <li key={c.id} className="border dark:border-gray-600 rounded-lg p-3 bg-white dark:bg-gray-800 flex flex-col gap-2" data-testid={`constraint-row-${c.id}`}>
                  <div className="flex items-center gap-3">
                    <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                    <DaysBadge start={c.start_date} end={c.end_date} />
                    <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                    {statusBadge(c.status)}
                    {/* Only the first approval step (pending_commander) is cancelable —
                        see cancel_constraint in backend/app/services/constraints.py.
                        Once it reaches pending_duty_manager it can no longer be
                        withdrawn unilaterally, so hide the button to avoid a call
                        that would 400. */}
                    {(c.status === "pending" || c.status === "pending_commander") && (
                      <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                        {t("my_requests.cancel")}
                      </button>
                    )}
                  </div>
                  <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                </li>
```

The approved block (originally lines 252-259) becomes:

```tsx
                <li key={c.id} className="border border-green-200 dark:border-green-800 rounded-lg p-3 bg-green-50 dark:bg-green-950" data-testid={`constraint-row-${c.id}`}>
                  <div className="flex items-center gap-3">
                    <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                    <DaysBadge start={c.start_date} end={c.end_date} />
                    <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                    {statusBadge(c.status)}
                  </div>
                  <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                </li>
```

The rejected block (originally lines 270-279, including the
`decision_note` paragraph) becomes:

```tsx
                <li key={c.id} className="border border-red-200 dark:border-red-800 rounded-lg p-3 bg-red-50 dark:bg-red-950" data-testid={`constraint-row-${c.id}`}>
                  <div className="flex items-center gap-3">
                    <span dir="ltr" className="text-gray-700 dark:text-gray-200">{c.start_date} → {c.end_date}</span>
                    <DaysBadge start={c.start_date} end={c.end_date} />
                    <span className="text-gray-700 dark:text-gray-300 flex-1">{c.reason}</span>
                    {statusBadge(c.status)}
                  </div>
                  {c.decision_note && (
                    <p className="text-xs text-red-700 dark:text-red-400 mt-1">{t("my_requests.decision_note")}: {c.decision_note}</p>
                  )}
                  <AuditHistoryBlock entityType="personal_constraint" entityId={c.id} />
                </li>
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npm test -- MyRequestsPage`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ExemptionInstanceModal.tsx frontend/src/components/ExemptionInstanceModal.test.tsx frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/MyRequestsPage.test.tsx
git commit -m "feat: embed inline audit history on exemption and constraint record UIs"
```

---

## Verification

Run the full backend and frontend suites and confirm all green before
considering this batch done:

```bash
# Backend (from backend/, venv activated)
pytest -q                    # full fast suite
pytest -m misc -q            # this batch's area
pytest -m duty -q            # exemptions/constraints area — must show no regressions

# Frontend (from frontend/)
npm test
npm run lint
npm run typecheck
```

"Done" for this batch means:
- `GET /api/audit-logs?entity_type=&entity_id=` exists, is scoped by the
  same authorization rules as the existing exemption/constraint detail
  endpoints, rejects unsupported `entity_type` values with 400, and
  correctly resolves history for a canceled (hard-deleted)
  `PersonalConstraint` via its audit trail.
- The exemption detail modal (`ExemptionInstanceModal`) and every
  constraint row on `MyRequestsPage` show a collapsed-by-default "הצג
  היסטוריה" toggle that lazily fetches and renders actor name, translated
  action, and timestamp per entry.
- No global audit-log admin page was added.
- `backend/app/audit/writer.py` was not modified.
- All backend and frontend suites listed above pass with no new failures.
