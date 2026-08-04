# Bug Report Feedback Modal Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the standalone `/my-bug-reports` page into the floating feedback button's modal as a second tab, with an unseen-activity badge on both the tab and the trigger button, and make bug-report reply notifications open that tab directly instead of navigating to a route.

**Architecture:** A new `BugReportModalProvider` React context (mirroring the existing `SoldierModalContext` pattern) owns the feedback modal's open/closed state above the router `<Routes>` tree, so it survives page navigation and can be triggered from anywhere (the floating button, the notification bell, the notifications page). `BugReportModal` gains two tabs — the existing "new report" form (unchanged behavior) and a new "my reports" tab (`BugReportMyReportsTab`, extracted from the page being deleted). The backend adds a `reporter_last_seen_at` column on `bug_reports` and a `POST /bug-reports/{id}/seen` + `GET /my/bug-reports/unseen-count` endpoint pair, following this codebase's existing `POST /algorithm/jobs/{id}/seen` convention.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, React, TypeScript, TanStack Query, React Router, Vitest, React Testing Library, pytest.

## Global Constraints

- Hebrew UI strings; English code identifiers.
- The comments rule remains reporter-or-admin; users must never receive another user's reports.
- The unseen-activity badge is scoped entirely to the reporter's own view — no equivalent signal is added for admins.
- A report's badge clears **per-report**, only when that specific report's thread is expanded (or the reporter posts their own reply to it) — never merely by opening the tab or the modal.
- Do NOT commit directly to `dev` or `master` — this plan executes on the `feature/bug-report-feedback-modal-tabs` branch/worktree.
- Preserve existing `BugReportModal` submit behavior (severity default, Ctrl+Enter submit, screenshot fallback text, mobile scroll layout) byte-for-byte on the "new" tab.

---

### Task 1: Backend — unseen-activity tracking column and endpoints

**Files:**
- Modify: `backend/app/db/models.py` (`BugReport`)
- Create: `backend/alembic/versions/<new>_add_reporter_last_seen_at.py`
- Modify: `backend/app/routes/bug_reports.py` (`BugReportSummaryOut`, `_summary_out`, `_summary_with_comment_aggregates`, `list_my_bug_reports`, `create_bug_report_comment`)
- Modify: `backend/app/services/notifications.py` (`_FRONTEND_PATHS`, `_frontend_url`)
- Test: `backend/app/routes/tests/test_bug_reports.py`

**Interfaces:**
- `BugReport.reporter_last_seen_at: datetime | None` — new nullable column.
- `BugReportSummaryOut.has_unseen_activity: bool` — new field, `False` unless computed by `list_my_bug_reports`.
- `POST /bug-reports/{report_id}/seen` — 204, reporter-only (not admin), sets `reporter_last_seen_at = now()`.
- `GET /my/bug-reports/unseen-count` — `{"count": int}`, the caller's own bug reports with unseen activity.
- `_frontend_url` for `bug_report_comment` notifications now builds `<frontend_url>/?bugReport=<id>` instead of `<frontend_url>/my-bug-reports?report=<id>` (the route is removed in Task 8; push/email links must still resolve to something the SPA can open).

- [ ] **Step 1: Write failing backend tests**

Add to `backend/app/routes/tests/test_bug_reports.py`:

```python
def test_bug_report_has_no_unseen_activity_when_reporter_never_left(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugseen001")
    _submit(client, reporter)

    resp = client.get("/api/my/bug-reports", headers=auth_headers(reporter))
    assert resp.status_code == 200
    assert resp.json()["items"][0]["has_unseen_activity"] is False


def test_bug_report_is_unseen_after_someone_elses_comment(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugseen002", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugseen003")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    client.post(f"/api/bug-reports/{report_id}/comments", json={"body": "looking into it"}, headers=auth_headers(admin))

    resp = client.get("/api/my/bug-reports", headers=auth_headers(reporter))
    assert resp.json()["items"][0]["has_unseen_activity"] is True


def test_bug_report_is_not_unseen_when_only_the_reporter_commented(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugseen004")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    client.post(f"/api/bug-reports/{report_id}/comments", json={"body": "adding detail"}, headers=auth_headers(reporter))

    resp = client.get("/api/my/bug-reports", headers=auth_headers(reporter))
    assert resp.json()["items"][0]["has_unseen_activity"] is False


def test_bug_report_is_unseen_after_status_change(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugseen005", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugseen006")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    client.patch(f"/api/admin/bug-reports/{report_id}", json={"status": "in_progress"}, headers=auth_headers(admin))

    resp = client.get("/api/my/bug-reports", headers=auth_headers(reporter))
    assert resp.json()["items"][0]["has_unseen_activity"] is True


def test_marking_a_bug_report_seen_clears_its_unseen_activity(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugseen007", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugseen008")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    client.post(f"/api/bug-reports/{report_id}/comments", json={"body": "hi"}, headers=auth_headers(admin))

    seen_resp = client.post(f"/api/bug-reports/{report_id}/seen", headers=auth_headers(reporter))
    assert seen_resp.status_code == 204

    resp = client.get("/api/my/bug-reports", headers=auth_headers(reporter))
    assert resp.json()["items"][0]["has_unseen_activity"] is False


def test_marking_seen_is_reporter_only_not_admin(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugseen009", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugseen010")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(f"/api/bug-reports/{report_id}/seen", headers=auth_headers(admin))
    assert resp.status_code == 403


def test_unseen_count_reflects_only_the_callers_own_unseen_reports(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugseen011", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugseen012")
    other_reporter = create_soldier(admin_session, personal_number="bugseen013")
    _submit(client, reporter, description="seen one")
    _submit(client, reporter, description="unseen one")
    _submit(client, other_reporter, description="other reporter own report")
    reports = {
        report.description: report
        for report in admin_session.query(BugReport).filter(BugReport.reporter_id.in_([reporter.id, other_reporter.id])).all()
    }
    seen_id = reports["seen one"].id
    unseen_id = reports["unseen one"].id
    other_id = reports["other reporter own report"].id
    client.post(f"/api/bug-reports/{seen_id}/comments", json={"body": "x"}, headers=auth_headers(admin))
    client.post(f"/api/bug-reports/{seen_id}/seen", headers=auth_headers(reporter))
    client.post(f"/api/bug-reports/{unseen_id}/comments", json={"body": "y"}, headers=auth_headers(admin))
    client.post(f"/api/bug-reports/{other_id}/comments", json={"body": "z"}, headers=auth_headers(admin))

    resp = client.get("/api/my/bug-reports/unseen-count", headers=auth_headers(reporter))
    assert resp.status_code == 200
    assert resp.json() == {"count": 1}
```

- [ ] **Step 2: Run the focused backend tests to confirm they fail**

Run: `pytest backend/app/routes/tests/test_bug_reports.py -k "unseen or seen" -q`
Expected: FAIL — `has_unseen_activity` key missing from the response, `/seen` and `/unseen-count` routes return 404.

- [ ] **Step 3: Add the column**

In `backend/app/db/models.py`, inside `class BugReport(Base):`, add after `updated_at`:

```python
    reporter_last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
```

Create `backend/alembic/versions/<new>_add_reporter_last_seen_at.py` (use `alembic revision -m "add reporter_last_seen_at to bug_reports"` from `backend/` with the venv active to get a real generated revision id, then fill in the body — do not hand-pick a revision id):

```python
"""add reporter_last_seen_at to bug_reports

Revision ID: <generated>
Revises: dd52c6d4e839
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "dd52c6d4e839"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bug_reports",
        sa.Column("reporter_last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bug_reports", "reporter_last_seen_at")
```

Run `alembic upgrade head` from `backend/` (venv active) to apply it locally.

- [ ] **Step 4: Add `has_unseen_activity` to the summary schema and endpoints**

In `backend/app/routes/bug_reports.py`:

Add the field to `BugReportSummaryOut` (after `last_comment_at`):

```python
    last_comment_at: datetime | None
    has_unseen_activity: bool
```

Update `_summary_out` to accept and pass it through, defaulting to `False` (the admin listing doesn't compute it):

```python
def _summary_out(
    report: BugReport,
    *,
    comment_count: int,
    last_comment_at: datetime | None,
    has_unseen_activity: bool = False,
) -> BugReportSummaryOut:
    return BugReportSummaryOut(
        id=report.id,
        reporter_id=report.reporter_id,
        description=report.description,
        severity=report.severity,
        status=report.status,
        route=report.route,
        nav_history=report.nav_history,
        audit_snapshot=report.audit_snapshot,
        user_snapshot=report.user_snapshot,
        has_screenshot=report.screenshot is not None,
        created_at=report.created_at,
        updated_at=report.updated_at,
        comment_count=comment_count,
        last_comment_at=last_comment_at,
        has_unseen_activity=has_unseen_activity,
    )
```

`_summary_with_comment_aggregates` (used only by the admin `update_bug_report_status` call site) needs no change — it still calls `_summary_out` without `has_unseen_activity`, which now defaults to `False`.

Add a pure helper just above `list_my_bug_reports` for the unseen computation, so both `list_my_bug_reports` and the new `/unseen-count` endpoint share one definition:

```python
def _has_unseen_activity(report: BugReport, last_comment_at: datetime | None) -> bool:
    seen_at = report.reporter_last_seen_at
    unseen_comment = last_comment_at is not None and (seen_at is None or last_comment_at > seen_at)
    unseen_status = report.updated_at > report.created_at and (seen_at is None or report.updated_at > seen_at)
    return unseen_comment or unseen_status
```

Update `list_my_bug_reports` to pass it through:

```python
@router.get("/my/bug-reports", response_model=PaginatedBugReports)
def list_my_bug_reports(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PaginatedBugReports:
    """Reporters' own bug reports, reusing the same `_summary_out` serializer
    (and `BugReportSummaryOut`/`PaginatedBugReports` response shape) as
    `GET /admin/bug-reports` so the frontend can share one client-side type."""
    comment_aggregates = _comment_aggregates_subquery()
    rows = session.execute(
        select(
            BugReport,
            func.coalesce(comment_aggregates.c.comment_count, 0).label("comment_count"),
            comment_aggregates.c.last_comment_at,
        )
        .outerjoin(comment_aggregates, comment_aggregates.c.bug_report_id == BugReport.id)
        .where(BugReport.reporter_id == user.id)
        .order_by(BugReport.created_at.desc())
    ).all()
    return PaginatedBugReports(
        items=[
            _summary_out(
                report,
                comment_count=comment_count,
                last_comment_at=last_comment_at,
                has_unseen_activity=_has_unseen_activity(report, last_comment_at),
            )
            for report, comment_count, last_comment_at in rows
        ],
        total=len(rows),
    )


class UnseenCountOut(BaseModel):
    count: int


@router.get("/my/bug-reports/unseen-count", response_model=UnseenCountOut)
def get_my_bug_reports_unseen_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnseenCountOut:
    comment_aggregates = _comment_aggregates_subquery()
    rows = session.execute(
        select(BugReport, comment_aggregates.c.last_comment_at)
        .outerjoin(comment_aggregates, comment_aggregates.c.bug_report_id == BugReport.id)
        .where(BugReport.reporter_id == user.id)
    ).all()
    count = sum(1 for report, last_comment_at in rows if _has_unseen_activity(report, last_comment_at))
    return UnseenCountOut(count=count)
```

Add the "seen" endpoint after `_require_reporter_or_admin` (it deliberately does **not** reuse that helper — marking a report seen mutates reporter-perspective state that has no meaning for an admin caller, so it must be reporter-only, not reporter-or-admin):

```python
@router.post("/bug-reports/{report_id}/seen", status_code=status.HTTP_204_NO_CONTENT)
def mark_bug_report_seen(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    report = session.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if report.reporter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    report.reporter_last_seen_at = datetime.now(UTC)
    session.commit()
```

Update `create_bug_report_comment` so the reporter's own reply also counts as "seen" (replacing the existing `if comment.author_id != report.reporter_id:` block):

```python
    if comment.author_id != report.reporter_id:
        create_notification(
            session,
            soldier_id=report.reporter_id,
            type=NotificationType.bug_report_comment,
            title="תגובה חדשה לדיווח באג",
            reference_type="bug_report",
            reference_id=report.id,
            actor_id=user.id,
        )
    else:
        report.reporter_last_seen_at = comment.created_at
    session.commit()
```

(This removes the old inner `session.commit()` that only ran in the notification branch — the single `session.commit()` above now unconditionally persists either the notification or the `reporter_last_seen_at` update.)

- [ ] **Step 5: Point the external (push/email) frontend link at `/` instead of the removed page**

In `backend/app/services/notifications.py`, change:

```python
    "bug_report_comment": "/my-bug-reports",
```
to:
```python
    "bug_report_comment": "/",
```

And update `_frontend_url`'s query param name to match the frontend's new convention (Task 3 reads `bugReport`, not `report`, to avoid any ambiguity with a bare `/` route):

```python
def _frontend_url(
    notification_type: NotificationType, reference_id: uuid.UUID | None = None
) -> str:
    from app.settings import get_settings
    base = get_settings().frontend_url.rstrip("/")
    path = _FRONTEND_PATHS.get(notification_type.value, "/notifications")
    if notification_type == NotificationType.bug_report_comment and reference_id is not None:
        path = f"{path}?bugReport={reference_id}"
    return f"{base}{path}"
```

- [ ] **Step 6: Run the focused backend tests and confirm they pass**

Run: `pytest backend/app/routes/tests/test_bug_reports.py -q`
Expected: all pass, including the new ones from Step 1.

Also run: `pytest backend/app/services/tests/test_notifications.py -q` (the existing `test_admin_comment_notifies_bug_report_owner`-style tests should still pass unchanged; if any test asserts the literal `_frontend_url` output for `bug_report_comment`, update its expected string to the new `/?bugReport=<id>` form).

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions backend/app/routes/bug_reports.py backend/app/services/notifications.py backend/app/routes/tests/test_bug_reports.py
git commit -m "feat: track and expose bug report unseen activity"
```

---

### Task 2: Frontend API layer

**Files:**
- Modify: `frontend/src/api/bugReports.ts`
- Modify: `frontend/src/api/notifications.ts`
- Modify: `frontend/src/queryKeys.ts`

**Interfaces:**
- `BugReportSummary.has_unseen_activity: boolean`
- `markBugReportSeen(reportId: string): Promise<void>`
- `getMyBugReportsUnseenCount(): Promise<{ count: number }>`
- `queryKeys.myBugReportsUnseenCount(): readonly ["bugReports", "unseenCount"]`
- `getNotificationLink` no longer returns a URL for `reference_type === "bug_report"` (returns `null` for that case — the caller special-cases it to open the modal instead).

- [ ] **Step 1: Update `frontend/src/api/bugReports.ts`**

Add `has_unseen_activity: boolean;` to `BugReportSummary` (after `last_comment_at`):

```typescript
export interface BugReportSummary {
  id: string;
  reporter_id: string;
  description: string;
  severity: BugReportSeverity;
  status: BugReportStatus;
  route: string;
  nav_history: NavHistoryEntry[] | null;
  audit_snapshot: Record<string, unknown>[] | null;
  user_snapshot: Record<string, unknown> | null;
  has_screenshot: boolean;
  created_at: string;
  updated_at: string;
  comment_count: number;
  last_comment_at: string | null;
  has_unseen_activity: boolean;
}
```

Add two new functions at the end of the file:

```typescript
export interface BugReportUnseenCount {
  count: number;
}

export async function markBugReportSeen(reportId: string): Promise<void> {
  await api.post(`/bug-reports/${reportId}/seen`);
}

export async function getMyBugReportsUnseenCount(): Promise<BugReportUnseenCount> {
  return (await api.get<BugReportUnseenCount>("/my/bug-reports/unseen-count")).data;
}
```

- [ ] **Step 2: Update `frontend/src/api/notifications.ts`**

Remove the `bug_report` branch from `getNotificationLink` (it no longer maps to a navigable route):

```typescript
export function getNotificationLink(
  n: Pick<NotificationDTO, "type" | "reference_type" | "reference_id">,
): string | null {
  if (n.reference_type === "algorithm_job" && n.reference_id) {
    return `/algorithm?jobId=${n.reference_id}`;
  }
  if (n.reference_type === "swap_request") {
    return n.type === "swap_offer" ? "/swaps?tab=incoming" : "/swaps?tab=mine";
  }
  if (n.reference_type === "personal_constraint" || n.reference_type === "exemption_request") {
    return "/my-requests";
  }
  if (n.reference_type === "duty_assignment") {
    return "/";
  }
  if ((n.reference_type === "range_event" || n.reference_type === "range_assignment") && n.reference_id) {
    return `/ranges?event=${n.reference_id}`;
  }
  return null;
}
```

- [ ] **Step 3: Add the query key**

In `frontend/src/queryKeys.ts`, add next to `myBugReports`:

```typescript
  myBugReports: () => ["bugReports", "mine"] as const,
  myBugReportsUnseenCount: () => ["bugReports", "unseenCount"] as const,
```

- [ ] **Step 4: Fix the one existing fixture that now needs the new required field**

`has_unseen_activity` is a new required field on `BugReportSummary`. `frontend/src/pages/admin/BugReportsContent.test.tsx` has exactly one place that constructs a full `BugReportSummary` object literal — `SAMPLE_REPORT` (around line 32) — every other fixture in that file spreads `...SAMPLE_REPORT`, so fixing this one constant fixes them all. Add the field:

```typescript
const SAMPLE_REPORT: BugReportSummary = {
  id: "r1",
  reporter_id: "s1",
  description: "the calendar is blank",
  severity: "high" as const,
  status: "open" as const,
  route: "/calendar",
  nav_history: [{ path: "/", timestamp: "2026-07-25T10:00:00Z" }],
  audit_snapshot: [{ action: "login", entity_type: "soldier" }],
  user_snapshot: { full_name: "Test Soldier" },
  has_screenshot: false,
  created_at: "2026-07-25T10:05:00Z",
  updated_at: "2026-07-25T10:05:00Z",
  comment_count: 2,
  last_comment_at: "2026-07-25T10:07:00Z",
  has_unseen_activity: false,
};
```

- [ ] **Step 5: Run typecheck**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS. If it fails anywhere else referencing `BugReportSummary` without `has_unseen_activity`, that's a fixture this research missed — add the field there too, the same way, before proceeding.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/bugReports.ts frontend/src/api/notifications.ts frontend/src/queryKeys.ts frontend/src/pages/admin/BugReportsContent.test.tsx
git commit -m "feat: add bug report unseen-activity API client functions"
```

---

### Task 3: `BugReportModalProvider` context

**Files:**
- Create: `frontend/src/contexts/BugReportModalContext.tsx`
- Create: `frontend/src/contexts/BugReportModalContext.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- `useBugReportModal(): { openBugReportModal: (opts?: { tab?: "new" | "mine"; reportId?: string; screenshot?: string | null }) => void }`
- Exported type `BugReportModalTab = "new" | "mine"`.
- The provider renders `<BugReportModal key={token} ... />` only while a modal is open, remounting on every `openBugReportModal` call (fresh `key`) so a second call while already open (e.g. a second notification click) always re-initializes tab/expanded state from the new arguments instead of being ignored by an already-mounted instance.
- On first mount, if the current URL has a `bugReport` search param (arriving from an external push/email link per Task 1 Step 5), the provider calls `openBugReportModal({ tab: "mine", reportId })` once and strips the param from the URL via `history.replaceState` (not a router navigation, to avoid disturbing whatever route the SPA actually landed on).

This task creates the provider only; `BugReportModal` does not yet accept the new props it expects (`initialTab`/`initialReportId`) — that lands in Task 6. Until Task 6, wire the provider to the *existing* `BugReportModal(screenshot, onClose)` signature so this task compiles and is independently testable; Task 6 extends the props.

- [ ] **Step 1: Write a failing test**

Create `frontend/src/contexts/BugReportModalContext.test.tsx`:

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { BugReportModalProvider, useBugReportModal } from "./BugReportModalContext";

vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn(),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
}));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

function Consumer() {
  const { openBugReportModal } = useBugReportModal();
  return <button onClick={() => openBugReportModal()} data-testid="open">open</button>;
}

describe("BugReportModalProvider", () => {
  it("renders no modal until openBugReportModal is called", () => {
    render(
      <MemoryRouter>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("bug-report-modal-overlay")).not.toBeInTheDocument();
  });

  it("opens the modal when openBugReportModal is called", async () => {
    render(
      <MemoryRouter>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("open"));
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
  });

  it("opens automatically from a bugReport query param on mount, then strips it from the URL", async () => {
    window.history.pushState({}, "", "/?bugReport=r1");
    render(
      <MemoryRouter initialEntries={["/?bugReport=r1"]}>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npx vitest run BugReportModalContext`
Expected: FAIL — `./BugReportModalContext` module doesn't exist yet.

- [ ] **Step 3: Implement the provider**

Create `frontend/src/contexts/BugReportModalContext.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from "react";
import BugReportModal from "../components/BugReportModal";

export type BugReportModalTab = "new" | "mine";

export interface OpenBugReportModalOptions {
  tab?: BugReportModalTab;
  reportId?: string;
  screenshot?: string | null;
}

interface BugReportModalContextValue {
  openBugReportModal: (opts?: OpenBugReportModalOptions) => void;
}

const BugReportModalContext = createContext<BugReportModalContextValue | null>(null);

export function useBugReportModal(): BugReportModalContextValue {
  const ctx = useContext(BugReportModalContext);
  if (!ctx) throw new Error("useBugReportModal used outside BugReportModalProvider");
  return ctx;
}

interface ModalState {
  token: number;
  tab: BugReportModalTab;
  reportId: string | null;
  screenshot: string | null;
}

export function BugReportModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalState | null>(null);
  const nextToken = useRef(0);

  const openBugReportModal = useCallback((opts: OpenBugReportModalOptions = {}) => {
    nextToken.current += 1;
    setModal({
      token: nextToken.current,
      tab: opts.tab ?? "new",
      reportId: opts.reportId ?? null,
      screenshot: opts.screenshot ?? null,
    });
  }, []);

  // External push/email links carry ?bugReport=<id> (see backend
  // _FRONTEND_PATHS) instead of a route, since the modal has no route of
  // its own. Open it once on first mount, then strip the param so it
  // doesn't re-trigger on an in-app refresh or get carried into a share.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reportId = params.get("bugReport");
    if (!reportId) return;
    openBugReportModal({ tab: "mine", reportId });
    params.delete("bugReport");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    window.history.replaceState(window.history.state, "", newUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleClose() {
    setModal(null);
  }

  return (
    <BugReportModalContext.Provider value={{ openBugReportModal }}>
      {children}
      {modal && (
        <BugReportModal
          key={modal.token}
          screenshot={modal.screenshot}
          onClose={handleClose}
        />
      )}
    </BugReportModalContext.Provider>
  );
}
```

(The `initialTab`/`initialReportId` props are added to `BugReportModal` — and passed here — in Task 6. Passing only `screenshot`/`onClose` for now keeps this task compiling against the current `BugReportModal` signature; the test above only asserts the overlay renders, which today's `BugReportModal` already satisfies.)

- [ ] **Step 4: Wire the provider into `App.tsx`**

In `frontend/src/App.tsx`, add the import next to `SoldierModalProvider`'s:

```typescript
import { SoldierModalProvider } from "./contexts/SoldierModalContext";
import { BugReportModalProvider } from "./contexts/BugReportModalContext";
```

Wrap the routes:

```tsx
          <SoldierModalProvider>
            <BugReportModalProvider>
              <Routes>
                ...
              </Routes>
            </BugReportModalProvider>
          </SoldierModalProvider>
```

(Indent the existing `<Routes>...</Routes>` block one level deeper to nest inside the new provider — do not otherwise change its contents in this task.)

- [ ] **Step 5: Run the test and typecheck**

Run: `npx vitest run BugReportModalContext`
Expected: PASS

Run (from `frontend/`): `npm run typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/contexts/BugReportModalContext.tsx frontend/src/contexts/BugReportModalContext.test.tsx frontend/src/App.tsx
git commit -m "feat: add global bug report modal context"
```

---

### Task 4: `BugReportTrigger` — use the context, add the badge

**Files:**
- Modify: `frontend/src/components/BugReportTrigger.tsx`
- Modify: `frontend/src/components/BugReportTrigger.test.tsx`

**Interfaces:**
- `BugReportTrigger` no longer holds its own `open`/`screenshot` state or renders `<BugReportModal>` — it calls `openBugReportModal({ tab: "new", screenshot })` from `useBugReportModal()`.
- Renders a numeric badge (`data-testid="bug-report-trigger-badge"`) when `getMyBugReportsUnseenCount()` (polled every 30s via `useQuery`, `queryKeys.myBugReportsUnseenCount()`) returns `count > 0`.

- [ ] **Step 1: Update the failing/changed assertions first**

Every existing test in `BugReportTrigger.test.tsx` asserts `document.body.querySelector('[data-testid="bug-report-modal-overlay"]')` appears after clicking — that will now only work if the component is rendered inside a `BugReportModalProvider`. Update the file's render calls (there are 7, all following the same two-line `render(<MemoryRouter>...<BugReportTrigger /></MemoryRouter>)` shape) to wrap with the provider, and mock the badge's API call. Rewrite the top of the file:

```typescript
import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportTrigger from "./BugReportTrigger";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import { toPng } from "html-to-image";

vi.mock("html-to-image", () => ({ toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA") }));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));
vi.mock("../api/bugReports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/bugReports")>()),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
}));

function renderTrigger() {
  return render(
    <MemoryRouter>
      <BugReportModalProvider>
        <BugReportTrigger />
      </BugReportModalProvider>
    </MemoryRouter>,
  );
}
```

Then replace every `render(<MemoryRouter><BugReportTrigger /></MemoryRouter>)` call in the remaining tests with `renderTrigger()`.

Add one new test at the end of the `describe` block:

```typescript
  test("shows a badge with the unseen-activity count", async () => {
    const { getMyBugReportsUnseenCount } = await import("../api/bugReports");
    vi.mocked(getMyBugReportsUnseenCount).mockResolvedValue({ count: 3 });

    renderTrigger();

    expect(await screen.findByTestId("bug-report-trigger-badge")).toHaveTextContent("3");
  });

  test("shows no badge when there is no unseen activity", async () => {
    renderTrigger();

    await waitFor(() => expect(screen.queryByTestId("bug-report-trigger")).toBeInTheDocument());
    expect(screen.queryByTestId("bug-report-trigger-badge")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `npx vitest run BugReportTrigger`
Expected: FAIL — `useBugReportModal used outside BugReportModalProvider` (or similar) once Step 3 below wires the hook in, and the badge tests fail because it doesn't exist yet. (If run before Step 3's implementation change, they'll instead fail because the provider wrapper is now required by the test file but the component doesn't use the context yet — either way, confirm red before proceeding.)

- [ ] **Step 3: Update the component**

Rewrite `frontend/src/components/BugReportTrigger.tsx`:

```tsx
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Bug, Loader2 } from "lucide-react";
import { toPng } from "html-to-image";
import { useBugReportModal } from "../contexts/BugReportModalContext";
import { getMyBugReportsUnseenCount } from "../api/bugReports";
import { queryKeys } from "../queryKeys";

// html-to-image inlines every font/image on the page as a base64 data URL before
// rasterizing, which can take a long time (or never settle at all) on content-heavy
// pages. Without a cap, a hang here would leave the trigger disabled forever with no
// way to open the modal — capping it means capture failure (including a hang) is
// always non-fatal, matching the rest of this feature's error handling.
const CAPTURE_TIMEOUT_MS = 6000;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("screenshot capture timed out")), ms);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (err) => { clearTimeout(timer); reject(err); },
    );
  });
}

export default function BugReportTrigger() {
  const { openBugReportModal } = useBugReportModal();
  const [capturing, setCapturing] = useState(false);
  // Other panels (e.g. the notifications dropdown) close themselves via a
  // document-level "mousedown outside" listener. That listener always runs
  // before this button's "click" event (mousedown precedes click in the
  // native event order), so starting capture on click would already see the
  // panel closed/unmounted. Starting capture on mousedown instead lets us
  // read the DOM while the panel is still open, since our own mousedown
  // handler (registered on the button itself) fires before the event bubbles
  // up to the document-level listener that closes the panel. triggeredRef
  // guards against double-firing for the same interaction (mousedown then
  // click) while still supporting keyboard activation (Enter/Space fire
  // click with no preceding mousedown).
  const triggeredRef = useRef(false);

  const unseenQuery = useQuery({
    queryKey: queryKeys.myBugReportsUnseenCount(),
    queryFn: getMyBugReportsUnseenCount,
    refetchInterval: 30000,
  });
  const unseenCount = unseenQuery.data?.count ?? 0;

  async function handleClick() {
    // Freeze the current scroll position before any async work.
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    setCapturing(true);
    let screenshot: string | null = null;
    try {
      // pixelRatio: 1 avoids multiplying the capture by devicePixelRatio, which is
      // often the single biggest driver of an oversized PNG on retina/high-DPI
      // displays. width/height clamp the capture to the viewport instead of the
      // full document — but clamping alone would always crop starting at the top
      // of the document (a previously-seen bug: scrolled pages showed only the
      // header). The clone is shifted up by the current scroll offset via
      // `style.transform` so the SVG foreignObject (which clips to width/height)
      // reveals the section of the page actually on screen, not the top of it.
      // Capture happens BEFORE the modal opens/mounts, so the modal's own
      // dimming overlay and empty form are never present in document.body while
      // toPng reads it — otherwise the screenshot would show the modal itself
      // instead of the page the user is reporting a bug about.
      screenshot = await withTimeout(
        toPng(document.body, {
          pixelRatio: 1,
          width: window.innerWidth,
          height: window.innerHeight,
          style: { transform: `translate(${-scrollX}px, ${-scrollY}px)` },
        }),
        CAPTURE_TIMEOUT_MS,
      );
    } catch {
      // non-fatal (rejection or timeout): submission proceeds without a screenshot
      screenshot = null;
    } finally {
      setCapturing(false);
      openBugReportModal({ tab: "new", screenshot });
      // Safety net for mousedown without a following click (e.g. the mouse
      // is released outside the button) — don't leave the trigger stuck.
      triggeredRef.current = false;
    }
  }

  function trigger() {
    if (triggeredRef.current || capturing) return;
    triggeredRef.current = true;
    void handleClick();
  }

  return createPortal(
    <button
      onMouseDown={trigger}
      onClick={() => {
        if (triggeredRef.current) {
          triggeredRef.current = false;
          return;
        }
        trigger();
      }}
      aria-label={capturing ? "מצלם צילום מסך..." : "מצאתי באג"}
      className="fixed bottom-20 left-2 md:bottom-4 md:left-4 flex flex-col items-center gap-0.5 text-gray-500 hover:text-indigo-600 z-[100] disabled:opacity-60"
      data-testid="bug-report-trigger"
      disabled={capturing}
    >
      {capturing
        ? <Loader2 size={22} className="animate-spin" data-testid="bug-report-trigger-spinner" aria-hidden="true" />
        : <Bug size={22} />}
      <span className="text-[10px] leading-none">פידבק</span>
      {unseenCount > 0 && (
        <span
          className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center"
          data-testid="bug-report-trigger-badge"
        >
          {unseenCount > 99 ? "99+" : unseenCount}
        </span>
      )}
    </button>,
    document.body,
  );
}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `npx vitest run BugReportTrigger`
Expected: PASS (all 9 tests: the original 7 plus the 2 new badge tests). Note the modal itself will now render via `BugReportModalProvider` inside the test's own render tree, so the existing overlay assertions keep working unchanged.

Run (from `frontend/`): `npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BugReportTrigger.tsx frontend/src/components/BugReportTrigger.test.tsx
git commit -m "feat: open feedback modal via context and show unseen badge"
```

---

### Task 5: `BugReportMyReportsTab` component

**Files:**
- Create: `frontend/src/components/BugReportMyReportsTab.tsx`
- Create: `frontend/src/components/BugReportMyReportsTab.test.tsx`

**Interfaces:**
- `BugReportMyReportsTabProps = { expandedId: string | null; onToggle: (id: string | null) => void }` — controlled: the parent (`BugReportModal`, Task 6) owns which report is expanded, so switching modal tabs doesn't lose it.
- Expanding a report (a `null → id` transition via `onToggle`) calls `markBugReportSeen(id)`, then invalidates `queryKeys.myBugReports()` and `queryKeys.myBugReportsUnseenCount()`.
- Consumes `queryKeys.myBugReports()`, `getMyBugReports`, `BugReportCommentsPanel` — all pre-existing.

This extracts the list/expand rendering that currently lives in `frontend/src/pages/MyBugReportsPage.tsx` (which Task 8 deletes). The query-param-driven auto-expand and re-sync-on-navigation behavior that page had are replaced by `BugReportModal`'s remount-per-open design (Task 6) — this component does not need its own `useSearchParams` logic.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/BugReportMyReportsTab.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "../i18n";
import BugReportMyReportsTab from "./BugReportMyReportsTab";
import * as bugReportsApi from "../api/bugReports";
import type { BugReportSummary } from "../api/bugReports";

vi.mock("../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../api/bugReports")>("../api/bugReports");
  return {
    ...actual,
    getMyBugReports: vi.fn(),
    listComments: vi.fn(),
    markBugReportSeen: vi.fn().mockResolvedValue(undefined),
  };
});

const REPORT: BugReportSummary = {
  id: "r1",
  reporter_id: "s1",
  description: "the calendar is blank",
  severity: "high",
  status: "open",
  route: "/calendar",
  nav_history: [{ path: "/super-secret-nav-path", timestamp: "2026-07-25T10:00:00Z" }],
  audit_snapshot: [{ action: "login", entity_type: "soldier" }],
  user_snapshot: { full_name: "Internal Snapshot User", rank: "סמל" },
  has_screenshot: false,
  created_at: "2026-07-25T10:05:00Z",
  updated_at: "2026-07-25T10:05:00Z",
  comment_count: 0,
  last_comment_at: null,
  has_unseen_activity: false,
};

function renderTab(expandedId: string | null = null, onToggle = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BugReportMyReportsTab expandedId={expandedId} onToggle={onToggle} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({ items: [REPORT], total: 1 });
  vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);
});

describe("BugReportMyReportsTab", () => {
  it("renders the reporter's own bug reports", async () => {
    renderTab();
    expect(await screen.findByText("the calendar is blank")).toBeInTheDocument();
  });

  it("shows the empty state when the user has no bug reports", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({ items: [], total: 0 });
    renderTab();
    expect(await screen.findByText("לא דיווחת על באגים")).toBeInTheDocument();
  });

  it("renders the comments panel and calls onToggle when a row is expanded (controlled)", async () => {
    const onToggle = vi.fn();
    renderTab(null, onToggle);
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(onToggle).toHaveBeenCalledWith("r1");
  });

  it("renders the comments panel when expandedId matches a report", async () => {
    renderTab("r1");
    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    await waitFor(() => expect(bugReportsApi.listComments).toHaveBeenCalledWith("r1"));
  });

  it("calls onToggle(null) when an already-expanded row is clicked again", async () => {
    const onToggle = vi.fn();
    renderTab("r1", onToggle);
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(onToggle).toHaveBeenCalledWith(null);
  });

  it("marks the report seen when it is expanded", async () => {
    renderTab(null, vi.fn());
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    await waitFor(() => expect(bugReportsApi.markBugReportSeen).toHaveBeenCalledWith("r1"));
  });

  it("does not mark the report seen when collapsing it", async () => {
    renderTab("r1", vi.fn());
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(bugReportsApi.markBugReportSeen).not.toHaveBeenCalled();
  });

  it("shows an unseen indicator for a report with unseen activity", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({
      items: [{ ...REPORT, has_unseen_activity: true }],
      total: 1,
    });
    renderTab();

    expect(await screen.findByTestId("my-bug-report-unseen-r1")).toBeInTheDocument();
  });

  it("does not expose internal snapshots or navigation history even when a row is expanded", async () => {
    renderTab("r1");
    await screen.findByText("אין תגובות עדיין");

    expect(screen.queryByText("/super-secret-nav-path")).not.toBeInTheDocument();
    expect(screen.queryByText("Internal Snapshot User")).not.toBeInTheDocument();
    expect(screen.queryByText("login")).not.toBeInTheDocument();
  });

  it("never shows admin-only controls or import actions", async () => {
    renderTab();
    await screen.findByText("the calendar is blank");

    expect(screen.queryByTestId("bug-report-import-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^bug-report-status-/)).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^bug-report-view-json-/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npx vitest run BugReportMyReportsTab`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/BugReportMyReportsTab.tsx`:

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { queryKeys } from "../queryKeys";
import { getMyBugReports, markBugReportSeen, BugReportSeverity, BugReportStatus } from "../api/bugReports";
import { translateApiError } from "../utils/translateApiError";
import BugReportCommentsPanel from "./BugReportCommentsPanel";

const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

export interface BugReportMyReportsTabProps {
  expandedId: string | null;
  onToggle: (id: string | null) => void;
}

export default function BugReportMyReportsTab({ expandedId, onToggle }: BugReportMyReportsTabProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const query = useQuery({ queryKey: queryKeys.myBugReports(), queryFn: getMyBugReports });
  const reports = query.data?.items ?? [];

  const bugReportSeverityLabel = (severity: BugReportSeverity) => t(`bug_reports.severity_${severity}`);
  const bugReportStatusLabel = (status: BugReportStatus) => t(`bug_reports.status_${status}`);

  function handleToggle(reportId: string) {
    const collapsing = expandedId === reportId;
    onToggle(collapsing ? null : reportId);
    if (!collapsing) {
      // Fire-and-forget: marking a report "seen" clears its unread badge.
      // Failure here is non-fatal — the report simply stays flagged unread
      // until a future successful expand, which is an acceptable degrade.
      void markBugReportSeen(reportId)
        .then(() => {
          void qc.invalidateQueries({ queryKey: queryKeys.myBugReports() });
          void qc.invalidateQueries({ queryKey: queryKeys.myBugReportsUnseenCount() });
        })
        .catch(() => {});
    }
  }

  return (
    <div className="space-y-3">
      {query.isLoading && (
        <p className="text-sm text-gray-500" data-testid="my-bug-reports-loading">{t("app.loading")}</p>
      )}
      {query.isError && (
        <p className="text-sm text-red-500" data-testid="my-bug-reports-error">
          {translateApiError(query.error, t, t("my_bug_reports.load_error"))}
        </p>
      )}
      {!query.isLoading && !query.isError && reports.length === 0 && (
        <p className="text-sm text-gray-500" data-testid="my-bug-reports-empty">{t("bug_reports.none")}</p>
      )}
      {!query.isLoading && !query.isError && reports.length > 0 && (
        <ul className="space-y-2 text-sm" data-testid="my-bug-reports-list">
          {reports.map((report) => {
            const isExpanded = expandedId === report.id;
            return (
              <li
                key={report.id}
                className="border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800"
                data-testid={`my-bug-report-row-${report.id}`}
              >
                <button
                  type="button"
                  onClick={() => handleToggle(report.id)}
                  className="w-full flex items-center gap-3 p-3 text-right"
                  aria-expanded={isExpanded}
                  data-testid={`my-bug-report-expand-${report.id}`}
                >
                  <span dir="ltr" className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                    {new Date(report.created_at).toLocaleString("he-IL")}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${SEVERITY_COLORS[report.severity]}`}>
                    {bugReportSeverityLabel(report.severity)}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 shrink-0">
                    {bugReportStatusLabel(report.status)}
                  </span>
                  <span className="flex-1 truncate">{report.description}</span>
                  {report.has_unseen_activity && (
                    <span
                      className="w-2 h-2 rounded-full bg-red-500 shrink-0"
                      data-testid={`my-bug-report-unseen-${report.id}`}
                      aria-hidden="true"
                    />
                  )}
                  <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                    {report.comment_count} {t("bug_reports.comment_count")}
                  </span>
                  <span className="text-gray-400 shrink-0">{isExpanded ? "▲" : "▼"}</span>
                </button>
                {isExpanded && (
                  <div className="border-t dark:border-gray-600">
                    <BugReportCommentsPanel reportId={report.id} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `npx vitest run BugReportMyReportsTab`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BugReportMyReportsTab.tsx frontend/src/components/BugReportMyReportsTab.test.tsx
git commit -m "feat: extract the my-reports tab into a controlled component"
```

---

### Task 6: `BugReportModal` — tabbed restructure

**Files:**
- Modify: `frontend/src/components/BugReportModal.tsx`
- Modify: `frontend/src/components/BugReportModal.test.tsx`
- Modify: `frontend/src/contexts/BugReportModalContext.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- `BugReportModalProps` gains `initialTab?: BugReportModalTab` (default `"new"`) and `initialReportId?: string | null` (default `null`).
- New i18n keys: `bug_reports.tab_new`, `bug_reports.tab_mine`.
- The "new" tab's DOM structure, testids, and behavior are byte-identical to today (existing tests must pass unchanged).
- Adds `data-testid="bug-report-tab-new"`, `data-testid="bug-report-tab-mine"`, `data-testid="bug-report-tab-mine-badge"`.

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/he.json`, inside the `"bug_reports"` object, add:

```json
    "tab_new": "דיווח חדש",
    "tab_mine": "הדיווחים שלי",
```

- [ ] **Step 2: Add failing tests**

Step 4 below adds `useQuery` (for the unseen-count badge) to `BugReportModal`, unconditionally — every render, including the 7 pre-existing tests, will need a `QueryClientProvider` ancestor from this point on (today's file has none, because today's component doesn't use React Query at all). Fix this ahead of time by introducing a shared render helper and switching every existing `render(...)` call in the file to use it — this is a modification to the existing tests' render calls (their assertions stay unchanged), not exempted by "keep existing tests as-is."

At the top of `frontend/src/components/BugReportModal.test.tsx`, add the import and replace every one of the file's 7 existing `render(<MemoryRouter initialEntries={["/duty"]}><BugReportModal .../></MemoryRouter>)` call sites with a call to a new `renderModal(props)` helper that wraps in both `QueryClientProvider` and `MemoryRouter`:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
```

Add the helper near the top of the file, above the `describe` block:

```typescript
function renderModal(props: Partial<React.ComponentProps<typeof BugReportModal>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot={null} onClose={vi.fn()} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
```

Then replace every existing test's render call — e.g. change:
```tsx
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
      </MemoryRouter>,
    );
```
to:
```tsx
    renderModal({ screenshot: "data:image/png;base64,AAA" });
```
(and similarly for the one existing test that passes `screenshot={null}` explicitly — that's now the helper's default, so `renderModal()` with no args suffices there). Do this for all 7 existing render call sites; their subsequent assertions and interactions (`fireEvent`, `waitFor`, etc.) are unchanged.

The file currently has:

```typescript
vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn().mockResolvedValue(undefined),
}));
```

This mock factory fully replaces the module (it does not spread the real module), so the "mine" tab's dependencies (`getMyBugReportsUnseenCount`, `getMyBugReports`, and `listComments` — pulled in transitively via `BugReportMyReportsTab` → `BugReportCommentsPanel`) would otherwise hit the real, unmocked HTTP client and hang. Replace it with:

```typescript
vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn().mockResolvedValue(undefined),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
  createComment: vi.fn(),
  uploadCommentAttachment: vi.fn(),
  bugReportCommentAttachmentDownloadUrl: vi.fn(() => ""),
}));
```

(`createComment`/`uploadCommentAttachment`/`bugReportCommentAttachmentDownloadUrl` are only present so `BugReportCommentsPanel` — rendered inside an expanded "mine" tab report — doesn't throw on an undefined import; none of this task's new tests exercise them.)

Add new tests inside the `describe("BugReportModal", ...)` block, using the same `renderModal` helper:

```typescript
  test("defaults to the new-report tab", async () => {
    renderModal();
    expect(screen.getByTestId("bug-report-tab-new")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("bug-report-description")).toBeInTheDocument();
  });

  test("switches to the my-reports tab and shows the reporter's own reports", async () => {
    const { getMyBugReports } = await import("../api/bugReports");
    vi.mocked(getMyBugReports).mockResolvedValue({
      items: [{
        id: "r1", reporter_id: "s1", description: "my old report", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: false,
      }],
      total: 1,
    });

    renderModal();

    fireEvent.click(screen.getByTestId("bug-report-tab-mine"));

    expect(await screen.findByText("my old report")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-description")).not.toBeInTheDocument();
  });

  test("opens directly on the my-reports tab with a report expanded when given initialTab/initialReportId", async () => {
    const { getMyBugReports, listComments } = await import("../api/bugReports");
    vi.mocked(getMyBugReports).mockResolvedValue({
      items: [{
        id: "r1", reporter_id: "s1", description: "deep-linked report", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: true,
      }],
      total: 1,
    });
    vi.mocked(listComments).mockResolvedValue([]);

    renderModal({ initialTab: "mine", initialReportId: "r1" });

    expect(screen.getByTestId("bug-report-tab-mine")).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    await waitFor(() => expect(listComments).toHaveBeenCalledWith("r1"));
  });

  test("shows an unseen-count badge on the my-reports tab", async () => {
    const { getMyBugReportsUnseenCount } = await import("../api/bugReports");
    vi.mocked(getMyBugReportsUnseenCount).mockResolvedValue({ count: 2 });

    renderModal();

    expect(await screen.findByTestId("bug-report-tab-mine-badge")).toHaveTextContent("2");
  });
```

- [ ] **Step 3: Run the tests to confirm the new ones fail**

Run: `npx vitest run BugReportModal`
Expected: the pre-existing tests still pass; the 4 new tests fail (`bug-report-tab-new`/`bug-report-tab-mine` testids don't exist yet).

- [ ] **Step 4: Restructure the component**

Rewrite `frontend/src/components/BugReportModal.tsx`:

```tsx
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { translateApiError } from "../utils/translateApiError";
import { submitBugReport, getMyBugReportsUnseenCount } from "../api/bugReports";
import { useNavigationHistory } from "../hooks/useNavigationHistory";
import { useModalBackClose } from "../hooks/useModalBackClose";
import { queryKeys } from "../queryKeys";
import type { BugReportModalTab } from "../contexts/BugReportModalContext";
import BugReportMyReportsTab from "./BugReportMyReportsTab";

type Severity = "low" | "medium" | "high";

const SEVERITIES: { value: Severity; label: string }[] = [
  { value: "low", label: "נמוכה" },
  { value: "medium", label: "בינונית" },
  { value: "high", label: "גבוהה" },
];

interface BugReportModalProps {
  screenshot: string | null;
  initialTab?: BugReportModalTab;
  initialReportId?: string | null;
  onClose: () => void;
}

export default function BugReportModal({
  screenshot,
  initialTab = "new",
  initialReportId = null,
  onClose,
}: BugReportModalProps) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const location = useLocation();
  const navHistory = useNavigationHistory();
  const [activeTab, setActiveTab] = useState<BugReportModalTab>(initialTab);
  const [expandedReportId, setExpandedReportId] = useState<string | null>(initialReportId);
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<Severity>("medium");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  const unseenQuery = useQuery({
    queryKey: queryKeys.myBugReportsUnseenCount(),
    queryFn: getMyBugReportsUnseenCount,
    refetchInterval: 30000,
  });
  const unseenCount = unseenQuery.data?.count ?? 0;

  async function handleSubmit() {
    if (!description.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitBugReport({
        description: description.trim(),
        severity,
        screenshot: screenshot ? (screenshot.split(",")[1] ?? null) : null,
        route: location.pathname,
        nav_history: navHistory,
      });
      setSucceeded(true);
      setTimeout(onClose, 1200);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה בשליחת הדיווח"));
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[110] overflow-y-auto p-4"
      onClick={onClose}
      data-testid="bug-report-modal-overlay"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full flex flex-col max-h-[calc(100dvh-2rem)]"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
        data-testid="bug-report-modal-dialog"
      >
        <div className="flex justify-between items-center mb-3 shrink-0">
          <div className="flex gap-1" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "new"}
              onClick={() => setActiveTab("new")}
              className={`px-2 py-1 text-sm rounded ${
                activeTab === "new"
                  ? "bg-indigo-600 text-white"
                  : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`}
              data-testid="bug-report-tab-new"
            >
              {t("bug_reports.tab_new")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "mine"}
              onClick={() => setActiveTab("mine")}
              className={`relative px-2 py-1 text-sm rounded ${
                activeTab === "mine"
                  ? "bg-indigo-600 text-white"
                  : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`}
              data-testid="bug-report-tab-mine"
            >
              {t("bug_reports.tab_mine")}
              {unseenCount > 0 && (
                <span
                  className="absolute -top-1.5 -right-1.5 bg-red-500 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center"
                  data-testid="bug-report-tab-mine-badge"
                >
                  {unseenCount > 99 ? "99+" : unseenCount}
                </span>
              )}
            </button>
          </div>
          <button
            onClick={onClose}
            className="p-1 -m-1 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            aria-label="סגור"
            data-testid="bug-report-modal-close"
          >
            <X size={20} />
          </button>
        </div>

        {activeTab === "new" ? (
          succeeded ? (
            <p className="text-sm text-green-600" data-testid="bug-report-success">הדיווח נשלח בהצלחה, תודה!</p>
          ) : (
            <>
              <div className="min-h-0 overflow-y-auto" data-testid="bug-report-modal-content">
                <div className="mb-3">
                  {screenshot ? (
                    <img src={screenshot} alt="" className="w-full rounded border dark:border-gray-600" />
                  ) : (
                    <p className="text-xs text-gray-500">לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו</p>
                  )}
                </div>
                <textarea
                  className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      if (!submitting && description.trim()) void handleSubmit();
                    }
                  }}
                  maxLength={2000}
                  placeholder="מה קרה?"
                  data-testid="bug-report-description"
                />
                <div className="flex gap-2 mt-3" data-testid="bug-report-severity-picker">
                  {SEVERITIES.map((s) => (
                    <button
                      key={s.value}
                      type="button"
                      onClick={() => setSeverity(s.value)}
                      className={`flex-1 px-2 py-1 text-xs rounded border ${
                        severity === s.value
                          ? "bg-indigo-600 text-white border-indigo-600"
                          : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"
                      }`}
                      data-testid={`bug-report-severity-${s.value}`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
                {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
              </div>
              <div className="flex justify-end gap-2 mt-4 shrink-0" data-testid="bug-report-modal-actions">
                <button type="button" onClick={onClose} disabled={submitting} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">
                  ביטול
                </button>
                <button
                  type="button"
                  onClick={() => { void handleSubmit(); }}
                  disabled={submitting || !description.trim()}
                  className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                  data-testid="bug-report-submit"
                >
                  {submitting ? "שולח..." : "שליחה"}
                </button>
              </div>
            </>
          )
        ) : (
          <div className="min-h-0 overflow-y-auto" data-testid="bug-report-modal-content">
            <BugReportMyReportsTab expandedId={expandedReportId} onToggle={setExpandedReportId} />
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Update the provider to pass the new props**

In `frontend/src/contexts/BugReportModalContext.tsx`, update the rendered `<BugReportModal>` call:

```tsx
      {modal && (
        <BugReportModal
          key={modal.token}
          screenshot={modal.screenshot}
          initialTab={modal.tab}
          initialReportId={modal.reportId}
          onClose={handleClose}
        />
      )}
```

- [ ] **Step 6: Run all the affected tests and typecheck**

Run: `npx vitest run BugReportModal BugReportModalContext BugReportTrigger`
Expected: all PASS.

Run (from `frontend/`): `npm run typecheck && npm run lint`
Expected: PASS, zero warnings.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/BugReportModal.tsx frontend/src/components/BugReportModal.test.tsx frontend/src/contexts/BugReportModalContext.tsx frontend/src/i18n/he.json
git commit -m "feat: add a my-reports tab to the feedback modal"
```

---

### Task 7: Notification click handling opens the modal instead of navigating

**Files:**
- Modify: `frontend/src/components/NotificationBell.tsx`
- Modify: `frontend/src/components/NotificationBell.test.tsx`
- Modify: `frontend/src/pages/NotificationsPage.tsx`
- Modify: `frontend/src/pages/NotificationsPage.test.tsx`

**Interfaces:**
- Clicking a notification with `reference_type === "bug_report"` calls `openBugReportModal({ tab: "mine", reportId: n.reference_id })` instead of navigating.
- All other reference types are unaffected (still use `getNotificationLink` + `navigate`).

- [ ] **Step 1: Update `NotificationBell.test.tsx` to wrap renders with the provider**

The 3 existing tests in this file render `<NotificationBell />` inside just `<MemoryRouter>`. Since `NotificationBell` will call `useBugReportModal()` unconditionally, every render needs the provider too. Update the top of the file and every `render(...)` call:

`NotificationBell` itself doesn't use React Query (it polls via a plain `setInterval`, unchanged by this task), but `BugReportModal` — which the provider can render once a bug_report notification is clicked — does use `useQuery` for its unseen-count badge (added in Task 6). `renderBell()` needs a `QueryClientProvider` ancestor for that reason:

```typescript
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import NotificationBell from "./NotificationBell";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import * as notificationsApi from "../api/notifications";
import * as bugReportsApi from "../api/bugReports";

vi.mock("../api/notifications");
vi.mock("../api/bugReports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/bugReports")>()),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
}));

function renderBell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <BugReportModalProvider>
          <NotificationBell />
        </BugReportModalProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
```

Replace each of the 3 `render(<MemoryRouter><NotificationBell /></MemoryRouter>)` (one is split across two lines in the middle test) calls with `renderBell()`.

Add a new test to the existing `describe` block:

```typescript
  it("opens the bug report modal instead of navigating for a bug_report notification", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{ ...baseNotification, id: "n1", title: "תגובה חדשה", type: "bug_report_comment", reference_type: "bug_report", reference_id: "report-123" }],
      total: 1,
    });
    vi.mocked(notificationsApi.markRead).mockResolvedValue({ ...baseNotification, id: "n1", title: "תגובה חדשה", type: "bug_report_comment", is_read: true });
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({
      items: [{
        id: "report-123", reporter_id: "s1", description: "the modal opened", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: true,
      }],
      total: 1,
    });
    vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);

    renderBell();
    (await screen.findByTestId("notification-bell")).click();
    (await screen.findByText("תגובה חדשה")).click();

    expect(await screen.findByText("the modal opened")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `npx vitest run NotificationBell`
Expected: existing 3 tests currently fail too (provider missing) until Step 3/4 land; the new test fails regardless. Confirm red.

- [ ] **Step 3: Update `NotificationBell.tsx`**

Add the import and hook:

```typescript
import { useState, useEffect, useRef, type CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getUnreadCount, listNotifications, markRead, markAllRead, deleteNotification, getNotificationLink, NotificationDTO, NOTIFICATION_TYPE_ICONS } from "../api/notifications";
import { useBugReportModal } from "../contexts/BugReportModalContext";

export default function NotificationBell() {
  const { t } = useTranslation();
  const { openBugReportModal } = useBugReportModal();
  const [unread, setUnread] = useState(0);
```

(keep everything else in the component body unchanged up to the render, then add a handler function above the `return`:)

```typescript
  function handleNotificationClick(n: NotificationDTO) {
    void handleMarkRead(n.id);
    if (n.reference_type === "bug_report" && n.reference_id) {
      openBugReportModal({ tab: "mine", reportId: n.reference_id });
    } else {
      const link = getNotificationLink(n);
      if (link) navigate(link);
    }
    setOpen(false);
  }
```

Update the notification row rendering (replace the existing `{getNotificationLink(n) ? (...) : (...)}` block):

```tsx
                  <div className="flex-1 min-w-0">
                    {getNotificationLink(n) || (n.reference_type === "bug_report" && n.reference_id) ? (
                      <button
                        className="text-sm font-medium truncate text-right w-full hover:text-indigo-600"
                        onClick={() => handleNotificationClick(n)}
                      >
                        {n.title}
                      </button>
                    ) : (
                      <p className="text-sm font-medium truncate">{n.title}</p>
                    )}
                    {n.body && <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{n.body}</p>}
                  </div>
```

- [ ] **Step 4: Update `NotificationsPage.tsx`**

```typescript
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import { usePagePagination } from "../hooks/usePagePagination";
import { listNotifications, markRead, markAllRead, deleteNotification, getNotificationLink, NotificationDTO, NOTIFICATION_TYPE_ICONS } from "../api/notifications";
import { useBugReportModal } from "../contexts/BugReportModalContext";

export default function NotificationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { openBugReportModal } = useBugReportModal();
  const queryClient = useQueryClient();
```

Add a handler alongside the existing `handleMarkRead`/`handleMarkAll`/`handleDelete` functions:

```typescript
  function handleNotificationClick(n: NotificationDTO) {
    if (n.reference_type === "bug_report" && n.reference_id) {
      openBugReportModal({ tab: "mine", reportId: n.reference_id });
    } else {
      const link = getNotificationLink(n);
      if (link) navigate(link);
    }
  }
```

Update the row rendering (replace the existing `{getNotificationLink(n) ? (...) : (...)}` block):

```tsx
                  {getNotificationLink(n) || (n.reference_type === "bug_report" && n.reference_id) ? (
                    <button className={`text-right ${n.is_read ? "text-gray-600 dark:text-gray-300" : "font-semibold"}`} onClick={() => handleNotificationClick(n)}>{n.title}</button>
                  ) : (
                    <p className={`${n.is_read ? "text-gray-600 dark:text-gray-300" : "font-semibold"}`}>{n.title}</p>
                  )}
```

- [ ] **Step 5: Update `NotificationsPage.test.tsx`**

Replace the whole file's contents:

```typescript
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import "../i18n";
import NotificationsPage from "./NotificationsPage";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import { listNotifications } from "../api/notifications";
import * as bugReportsApi from "../api/bugReports";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("../api/notifications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/notifications")>()),
  listNotifications: vi.fn(),
}));

vi.mock("../api/bugReports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/bugReports")>()),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <BugReportModalProvider>
          <NotificationsPage />
        </BugReportModalProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    navigate.mockReset();
    vi.mocked(listNotifications).mockResolvedValue({
      items: [{
        id: "notification-1",
        soldier_id: "soldier-1",
        title: "תגובה חדשה לדיווח באג",
        body: null,
        type: "bug_report_comment",
        reference_type: "bug_report",
        reference_id: "report-123",
        is_read: false,
        created_at: "2026-08-03T12:00:00Z",
      }],
      total: 1,
    });
  });

  it("opens the referenced bug report in the feedback modal instead of navigating", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({
      items: [{
        id: "report-123", reporter_id: "s1", description: "opened from notifications page", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: true,
      }],
      total: 1,
    });
    vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "תגובה חדשה לדיווח באג" }));

    expect(await screen.findByText("opened from notifications page")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `npx vitest run NotificationBell NotificationsPage`
Expected: PASS

Run (from `frontend/`): `npm run typecheck && npm run lint`
Expected: PASS, zero warnings.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/NotificationBell.tsx frontend/src/components/NotificationBell.test.tsx frontend/src/pages/NotificationsPage.tsx frontend/src/pages/NotificationsPage.test.tsx
git commit -m "feat: open bug report notifications in the feedback modal"
```

---

### Task 8: Remove the old page, route, and links

**Files:**
- Delete: `frontend/src/pages/MyBugReportsPage.tsx`
- Delete: `frontend/src/pages/MyBugReportsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/pages/MyRequestsPage.test.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- No route registered at `/my-bug-reports`.
- No link to it from the profile page or "My Requests" page — the feedback modal (floating button, or a notification click) is the only entry point to "my reports" now.

- [ ] **Step 1: Delete the old page and its test**

```bash
git rm frontend/src/pages/MyBugReportsPage.tsx frontend/src/pages/MyBugReportsPage.test.tsx
```

- [ ] **Step 2: Remove the route from `App.tsx`**

Remove the import:
```typescript
import MyBugReportsPage from "./pages/MyBugReportsPage";
```

Remove the route:
```typescript
                <Route path="/my-bug-reports" element={<AppGate><MyBugReportsPage /></AppGate>} />
```

- [ ] **Step 3: Remove the profile page link**

In `frontend/src/pages/ProfilePage.tsx`, remove:

```tsx
        <Link to="/my-bug-reports" className="text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200" data-testid="profile-my-bug-reports">
          {t("profile.my_bug_reports")}
        </Link>
```

(`Link` is still used elsewhere on this page for `profile-change-password` — do not remove its import.)

- [ ] **Step 4: Remove the "My Requests" page link**

In `frontend/src/pages/MyRequestsPage.tsx`, remove the entire block:

```tsx
        <div className="pt-4 border-t dark:border-gray-600">
          <Link
            to="/my-bug-reports"
            className="text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200 text-sm"
            data-testid="my-requests-bug-reports-link"
          >
            {t("profile.my_bug_reports")}
          </Link>
        </div>
```

This was the only use of `Link` in this file (confirmed: `Link` appears at line 3's import and at this one now-removed usage, nowhere else) — remove its now-unused import too:
```typescript
import { Link } from "react-router-dom";
```

- [ ] **Step 5: Update `MyRequestsPage.test.tsx`**

`MemoryRouter` in this test file exists solely because of the `<Link>` just removed — `MyRequestsPage.tsx` uses no other router hooks (confirmed: no `useNavigate`, no other `react-router-dom` import in that file). Remove the now-unnecessary wrapper. Change the `renderPage` helper (around line 73) from:

```tsx
function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <MyRequestsPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}
```

to:

```tsx
function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MyRequestsPage />
    </QueryClientProvider>
  );
}
```

And remove the now-unused `import { MemoryRouter } from "react-router-dom";` line near the top of the file.

- [ ] **Step 6: Clean up now-unused i18n keys**

In `frontend/src/i18n/he.json`:
- Remove `"title": "הדיווחים שלי על באגים",` from the `"my_bug_reports"` object (keep `"load_error"` — it's still used by `BugReportMyReportsTab`).
- Remove `"my_bug_reports": "הדיווחים שלי על באגים",` from the `"profile"` object (its only two consumers were the two links just deleted).

- [ ] **Step 7: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`):
```bash
npm test
npm run lint
npm run typecheck
```
Expected: all PASS (confirmed during this plan's research: `MyRequestsPage.test.tsx` has no positive assertion on the removed `my-requests-bug-reports-link` testid, so no further test changes are needed there beyond Step 5 above).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove the standalone my-bug-reports page and its links"
```

---

### Task 9: Full verification

**Files:**
- No planned source changes; fix only if verification exposes a directly related regression.

- [ ] **Step 1: Run the full backend suite**

From `backend/` (venv active): `pytest -q`
Expected: all pass (matches the repo's documented pre-existing skip pattern for 3 solver "no proposals" tests, unrelated to this change).

- [ ] **Step 2: Run the full frontend suite, lint, and typecheck**

From `frontend/`:
```bash
npm test
npm run lint
npm run typecheck
```
Expected: all PASS, zero ESLint warnings.

- [ ] **Step 3: Manually verify `alembic upgrade head` applies cleanly from a fresh check**

From `backend/` (venv active): `alembic upgrade head`
Expected: no errors; `alembic current` shows the new migration as head.

- [ ] **Step 4: Check `git status` and `git diff --check`**

```bash
git status
git diff --check
```
Expected: clean, no whitespace errors, no unexpected untracked files.

- [ ] **Step 5: Review the branch log and prepare for `merge-worktree-to-dev`**

```bash
git log --oneline dev..HEAD
```
Do not merge or push without the user's explicit release/integration instruction — hand off to the project's `merge-worktree-to-dev` skill when asked.
