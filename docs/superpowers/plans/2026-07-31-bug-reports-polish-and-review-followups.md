# Bug Reports Polish + Review Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 14 minor findings logged from a prior batch's code reviews (2 already turned out to be pre-resolved — see Global Constraints), and rebuild the bug-reports admin table on the shared `DataTable` component (sortable + filterable columns) with a new status-icon-button row UI that colors each row by status, replacing the current per-row `<select>`.

**Architecture:** Small independent backend/frontend hardening fixes come first (notification dedup, DB indexes, upload caps, a11y, pagination clamping, misc polish), since they're low-risk and unblock nothing else. The table rework is split into two tasks: first migrate `BugReportsContent.tsx`'s hand-rolled `<table>` onto `DataTable` (which already provides per-column sorting and a checkbox-style column filter, confirmed by investigation to be a mechanically straightforward fit given `DataTable`'s existing `expandable` prop matches the current expand-row behavior), then replace the status `<select>` with icon buttons and add per-status row background color on top of that.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic (backend), React/TypeScript/Tailwind (frontend), pytest, vitest.

## Global Constraints

- Hebrew UI strings only for new text — prefer existing `bug_reports.status_*`/`severity_*` i18n keys over new hardcoded literals; add new keys to `frontend/src/i18n/he.json` only when no existing key fits.
- Two of the originally-logged 14 findings are **already resolved** — do not re-fix them, just confirm on sight:
  - "list_locations auth widening needs conscious sign-off" — `backend/app/routes/duty_config.py:302-309` already has an explanatory comment justifying the choice (reference-data precedent matching `list_duty_types`). No task needed.
  - "Catch-all route is broader scope than the fix required" — `frontend/src/App.tsx:121-124` already has an explanatory comment ("Safety net: an unmatched authenticated URL... should land somewhere real"). No task needed.
- Run the project's targeted test commands per task (not the full suite) — see each task's Global Constraints line.
- Follow existing code style in each touched file.

---

## File Structure

- **Modify:** `backend/app/services/swaps.py` — dedup requester-side notification in `approve_soldier_side`.
- **Create:** `backend/alembic/versions/<rev>_add_bug_report_comment_indexes.py` — indexes migration.
- **Modify:** `backend/app/db/models.py` — add `index=True` to the two FK columns.
- **Modify:** `backend/app/routes/bug_reports.py` — comment/attachment count caps, bounded-read attachment upload.
- **Modify:** `backend/tests/conftest.py` — add the two new tables to `_ALL_DATA_TABLES`.
- **Modify:** `frontend/src/components/PopoverDropdown.tsx` — gate listener on `open`, add Escape-to-close, add `aria-expanded`/`aria-haspopup`.
- **Modify:** `frontend/src/pages/admin/BugReportsContent.tsx`, `frontend/src/pages/AnnouncementsPage.tsx`, `frontend/src/pages/NotificationsPage.tsx` — clamp `page` to valid range.
- **Modify:** `frontend/src/App.tsx` — clarifying comment on `TelegramGate`'s fail-open behavior; same for `hakpazaEnabled`.
- **Create:** `frontend/src/components/dashboard/DutyTypeBreakdownChart.test.tsx`.
- **Move:** `frontend/src/pages/admin/BugReportDetailModal.tsx` → `frontend/src/components/BugReportDetailModal.tsx`; update both import sites.
- **Modify:** `frontend/src/components/BugReportDetailModal.tsx` (post-move) — `AttachmentThumbnail` fallback UI on fetch failure; attachment-upload retry affordance.
- **Modify:** `frontend/src/pages/admin/BugReportsContent.tsx` — migrate to `DataTable`; replace hardcoded `STATUS_LABELS`/`SEVERITY_LABELS` with existing i18n keys; replace status `<select>` with icon buttons; per-status row background color.
- **Test:** targeted new/updated test files per task, listed within each task.

---

### Task 1: Dedup swap "awaiting manager decision" notification

**Files:**
- Modify: `backend/app/services/swaps.py` (`approve_soldier_side`, lines ~489-512; `_notify_awaiting_manager_decision`, lines ~365-396)
- Test: `backend/tests/unit/test_swaps_service.py`

**Interfaces:**
- No signature changes — internal dedup only.

- [ ] **Step 1: Write the failing test**

Read `backend/tests/unit/test_swaps_service.py`'s existing swap-notification tests first for fixture conventions (this file already has a `test_swap_fully_candidate_approved_notifies_duty_managers`-style test from prior work — match its setup style). Add:

```python
def test_approve_soldier_side_does_not_duplicate_requester_notification_across_candidates(
    session, make_soldier, make_hierarchy_node, make_duty_assignment, make_swap_request, make_swap_candidate
):
    # Adjust to match this file's actual fixture helper names/signatures.
    node = make_hierarchy_node(name="Test Node")
    duty_manager = make_soldier(hierarchy_node_id=node.id)
    requester = make_soldier(hierarchy_node_id=node.id)
    assignment = make_duty_assignment(soldier=requester)
    req = make_swap_request(requester=requester, assignment=assignment)
    candidate_a = make_swap_candidate(request=req, soldier=make_soldier(hierarchy_node_id=node.id))
    candidate_b = make_swap_candidate(request=req, soldier=make_soldier(hierarchy_node_id=node.id))

    approve_soldier_side(session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)

    notifications = session.execute(
        select(Notification).where(
            Notification.notification_type == NotificationType.swap_pending_approval,
            Notification.soldier_id == duty_manager.id,
        )
    ).scalars().all()
    assert len(notifications) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_swaps_service.py -k "does_not_duplicate_requester" -v`
Expected: FAIL — `len(notifications) == 2`

- [ ] **Step 3: Fix the dedup**

Read the exact current loop body in `approve_soldier_side` (lines ~489-512) first. The requester-side half of `_notify_awaiting_manager_decision` only depends on `req`, not on the per-candidate loop variable — move that call out of the per-candidate loop so it fires once per `approve_soldier_side` invocation, while the covering-side notification (which does vary per candidate, lines ~387-395) stays inside the loop. Read `_notify_awaiting_manager_decision`'s full body first to confirm it's safe to split into a requester-side call and a covering-side call, or extract two smaller helpers if that's cleaner — match whichever refactor keeps the function's existing behavior for the covering side identical.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_swaps_service.py -k "does_not_duplicate_requester" -v`
Expected: PASS

- [ ] **Step 5: Run the swaps test files for regressions**

Run: `cd backend && pytest tests/unit/test_swaps_service.py tests/unit/test_swaps.py -q`
Expected: PASS, no regressions (in particular, confirm the existing chain-handoff and both-sides-approved notification tests from the prior batch still pass — this refactor must not silently drop the covering-side notification)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "fix: don't duplicate the requester-side swap notification across multiple candidates"
```

---

### Task 2: Bug-report backend hardening (indexes, count caps, bounded upload read, conftest table list)

**Files:**
- Modify: `backend/app/db/models.py` (`BugReportComment.bug_report_id`, `BugReportCommentAttachment.comment_id`)
- Create: `backend/alembic/versions/<rev>_add_bug_report_comment_indexes.py`
- Modify: `backend/app/routes/bug_reports.py` (`create_bug_report_comment`, `upload_bug_report_comment_attachment`)
- Modify: `backend/tests/conftest.py` (`_ALL_DATA_TABLES`)
- Test: `backend/app/routes/tests/test_bug_reports.py`

**Interfaces:**
- Produces: comment creation returns `429`/`400` (pick whichever status this codebase already uses for a "too many X" rejection — check `backend/app/routes/` for precedent, e.g. rate-limit responses, before choosing) when a report already has 200+ comments, or a comment already has 10+ attachments (numbers are reasonable defaults — confirm no existing product-defined cap exists elsewhere before picking these).

- [ ] **Step 1: Add indexes**

In `backend/app/db/models.py`, add `index=True` to both FK columns:

```python
# BugReportComment
bug_report_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("bug_reports.id", ondelete="CASCADE"), index=True
)

# BugReportCommentAttachment
comment_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("bug_report_comments.id", ondelete="CASCADE"), index=True
)
```

- [ ] **Step 2: Generate and apply the migration**

Confirm exactly one migration head first: `cd backend && alembic heads` (expect one line — this repo's history has had branched migrations before).

Run: `cd backend && alembic revision -m "add indexes on bug report comment and attachment FKs"`

```python
from alembic import op

def upgrade() -> None:
    op.create_index(
        "ix_bug_report_comments_bug_report_id", "bug_report_comments", ["bug_report_id"]
    )
    op.create_index(
        "ix_bug_report_comment_attachments_comment_id", "bug_report_comment_attachments", ["comment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_bug_report_comment_attachments_comment_id", table_name="bug_report_comment_attachments")
    op.drop_index("ix_bug_report_comments_bug_report_id", table_name="bug_report_comments")
```

Run: `cd backend && alembic upgrade head`

- [ ] **Step 3: Write the failing tests for count caps**

Read `backend/app/routes/tests/test_bug_reports.py`'s existing comment tests first for fixture conventions. Add:

```python
def test_create_comment_rejected_after_report_hits_comment_cap(client, admin_token, make_bug_report):
    # Adjust to match real fixtures. Create MAX_COMMENTS_PER_REPORT comments first
    # (import the real constant from app.routes.bug_reports rather than
    # hardcoding 200, so this test stays correct if the constant changes),
    # then assert the next one is rejected.
    ...

def test_upload_attachment_rejected_after_comment_hits_attachment_cap(client, admin_token, make_bug_report):
    ...
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "cap" -v`
Expected: FAIL — caps don't exist yet

- [ ] **Step 5: Implement the caps**

In `backend/app/routes/bug_reports.py`, near the top with other module constants:

```python
MAX_COMMENTS_PER_REPORT = 200
MAX_ATTACHMENTS_PER_COMMENT = 10
```

In `create_bug_report_comment`, before `session.add(comment)`, add a count check:

```python
existing_count = session.execute(
    select(func.count()).select_from(BugReportComment).where(BugReportComment.bug_report_id == report_id)
).scalar_one()
if existing_count >= MAX_COMMENTS_PER_REPORT:
    raise HTTPException(status_code=400, detail="too_many_comments")
```

In `upload_bug_report_comment_attachment`, before reading the file, add the equivalent check against `BugReportCommentAttachment.comment_id == comment_id`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "cap" -v`
Expected: PASS

- [ ] **Step 7: Write the failing test for bounded-read (reject oversized before full buffering)**

```python
def test_upload_attachment_rejects_oversized_file_without_reading_entire_body(client, admin_token, make_bug_report):
    # Send a file whose declared/streamed size exceeds the 5MB cap. This test's
    # main point is behavioral (still 400/413 file_too_large), but the
    # implementation change (Step 8) should avoid `await file.read()` loading
    # the whole oversized body into memory first — verify by code review, not
    # by a memory-measuring test, since that's impractical in this test suite.
    ...
```

(This test asserts the same external behavior as before — it exists to guard the refactor in Step 8 from accidentally changing the response, not to newly test something unobservable from outside.)

- [ ] **Step 8: Switch to a bounded read**

In `upload_bug_report_comment_attachment`, replace the unconditional `data = await file.read()` with a bounded read that stops early once the size cap is exceeded, following the same pattern already used in `import_bug_reports` (`backend/app/routes/bug_reports.py`, which does `f.file.read(_MAX_IMPORT_FILE_BYTES + 1)` — read that function first for the exact pattern):

```python
data = await file.read(_MAX_COMMENT_ATTACHMENT_BYTES + 1)
if len(data) > _MAX_COMMENT_ATTACHMENT_BYTES:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_too_large")
```

(Confirm `UploadFile.read()` accepts a size argument and that this doesn't break the subsequent magic-byte validation, which only needs the bytes already read.)

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -k "oversized" -v`
Expected: PASS

- [ ] **Step 10: Add the two tables to conftest's truncation list**

In `backend/tests/conftest.py`, add to `_ALL_DATA_TABLES` (near `"bug_reports"`):

```python
"bug_report_comments",
"bug_report_comment_attachments",
```

- [ ] **Step 11: Run the full bug-reports test file for regressions**

Run: `cd backend && pytest app/routes/tests/test_bug_reports.py -q`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/ backend/app/routes/bug_reports.py backend/tests/conftest.py backend/app/routes/tests/test_bug_reports.py
git commit -m "fix: add indexes, count caps, and bounded-read upload for bug report comments/attachments"
```

---

### Task 3: `PopoverDropdown` accessibility polish

**Files:**
- Modify: `frontend/src/components/PopoverDropdown.tsx`
- Test: `frontend/src/components/PopoverDropdown.test.tsx` (extend existing)

**Interfaces:**
- No prop changes — internal behavior only.

- [ ] **Step 1: Write the failing tests**

Read the existing `PopoverDropdown.test.tsx` first to match conventions. Add:

```tsx
it("closes on Escape key when open", () => {
  render(<PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div>תוכן</div>}</PopoverDropdown>);
  fireEvent.click(screen.getByText("סנן"));
  expect(screen.getByText("תוכן")).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByText("תוכן")).not.toBeInTheDocument();
});

it("sets aria-expanded to reflect open state", () => {
  render(<PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div />}</PopoverDropdown>);
  const trigger = screen.getByText("סנן").closest("button")!;
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(trigger);
  expect(trigger).toHaveAttribute("aria-expanded", "true");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/PopoverDropdown.test.tsx`
Expected: FAIL — Escape does nothing, no `aria-expanded` attribute

- [ ] **Step 3: Gate the mousedown listener on `open`, add Escape handling, add aria attributes**

Read the exact current effect and trigger button JSX first. Following the already-correct sibling pattern in `frontend/src/components/DataTable.tsx`'s `CustomColumnFilterDropdown` (lines ~120-127, `if (!open) return;` + `[open]` dependency array) for the gating:

```tsx
useEffect(() => {
  if (!open) return;
  function onDocClick(e: MouseEvent) {
    if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") setOpen(false);
  }
  document.addEventListener("mousedown", onDocClick);
  document.addEventListener("keydown", onKeyDown);
  return () => {
    document.removeEventListener("mousedown", onDocClick);
    document.removeEventListener("keydown", onKeyDown);
  };
}, [open]);
```

And on the trigger `<button>`, add `aria-expanded={open}` and `aria-haspopup="true"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/PopoverDropdown.test.tsx`
Expected: PASS (all tests including new ones)

- [ ] **Step 5: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PopoverDropdown.tsx frontend/src/components/PopoverDropdown.test.tsx
git commit -m "fix: gate PopoverDropdown's outside-click listener on open state, add Escape-to-close and aria attributes"
```

---

### Task 4: Clamp pagination to the valid page range

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx`, `frontend/src/pages/AnnouncementsPage.tsx`, `frontend/src/pages/NotificationsPage.tsx`
- Test: manual (each page already has pagination covered indirectly by existing component tests; this is a small `useEffect` addition — add an assertion to an existing test file for one of the three pages if a lightweight fit exists, otherwise verify by code trace, consistent with this codebase's established practice for sandboxed-environment verification)

**Interfaces:**
- No hook changes — each page adds its own clamp effect since only the page knows `total`/`pages` once its query resolves.

- [ ] **Step 1: Add a clamp effect to each of the three pages**

In each file, after `const pages = Math.ceil(total / limit);`, add:

```tsx
useEffect(() => {
  if (pages > 0 && page > pages) setPage(pages);
}, [page, pages, setPage]);
```

(Guard `pages > 0` so this doesn't fire while `total` is still `0`/loading before the first query resolves — read each file's exact query-loading state first to confirm `total` defaults sensibly, e.g. `0` while loading vs. `undefined`, and adjust the guard if needed.)

- [ ] **Step 2: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, navigate to `/admin` bug reports (or announcements/notifications) with more than one page of results, manually edit the URL to a `?page=` value beyond the last page, confirm it snaps back to the last valid page instead of showing an empty list.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/AnnouncementsPage.tsx frontend/src/pages/NotificationsPage.tsx
git commit -m "fix: clamp pagination to the valid page range when a stale/out-of-range page param is present"
```

---

### Task 5: Document `TelegramGate`/hakpaza fail-open behavior

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: none (comment-only change)

- [ ] **Step 1: Add a clarifying comment above `TelegramGate`**

```tsx
// If usePublicSettings() has permanently failed to fetch (rather than still
// loading), `settings` resolves to `{}` (not `null`) — settingsLoaded becomes
// true and telegramEnabled becomes false, so this gate fails OPEN (lets the
// user through) rather than blocking them on a broken settings fetch. This
// is intentional: a settings-fetch outage should not lock users out of the
// app entirely.
function TelegramGate({ children }: { children: ReactElement }) {
```

- [ ] **Step 2: Add the equivalent comment near the `hakpazaEnabled` usage**

Locate the `hakpazaEnabled` line in `App()` (confirmed at investigation to have the same fail-open pattern) and add a one-line comment referencing the same reasoning (or point back to `TelegramGate`'s comment to avoid duplicating the full explanation).

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors (comment-only change, should be a no-op)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "docs: document intentional fail-open behavior when public settings fetch fails"
```

---

### Task 6: Add a test for `DutyTypeBreakdownChart`

**Files:**
- Create: `frontend/src/components/dashboard/DutyTypeBreakdownChart.test.tsx`
- Test: itself

- [ ] **Step 1: Write the test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DutyTypeBreakdownChart from "./DutyTypeBreakdownChart";

describe("DutyTypeBreakdownChart", () => {
  it("shows the empty-state message when there is no data with days > 0", () => {
    render(<DutyTypeBreakdownChart perType={[]} />);
    expect(screen.getByText("אין נתוני פירוט")).toBeInTheDocument();
  });

  it("filters out entries with 0 total days", () => {
    render(
      <DutyTypeBreakdownChart
        perType={[
          { duty_type_id: "1", duty_type_name: "שמירה", days: 0, days_past: 0, days_future: 0, score: "0" },
        ]}
      />
    );
    expect(screen.getByText("אין נתוני פירוט")).toBeInTheDocument();
  });

  it("renders a chart when at least one entry has days > 0", () => {
    render(
      <DutyTypeBreakdownChart
        perType={[
          { duty_type_id: "1", duty_type_name: "שמירה", days: 3, days_past: 2, days_future: 1, score: "10" },
        ]}
      />
    );
    expect(screen.queryByText("אין נתוני פירוט")).not.toBeInTheDocument();
  });
});
```

(Confirm the exact empty-state string and `BreakdownPerType` field names against the real component before finalizing — read `DutyTypeBreakdownChart.tsx` again if needed; recharts components sometimes need a fixed-size container or specific test-environment handling — check whether other chart-component tests in this codebase (e.g. any existing recharts-based component test) need extra setup like a mocked `ResizeObserver`, and match that pattern if so.)

- [ ] **Step 2: Run test**

Run: `cd frontend && npx vitest run src/components/dashboard/DutyTypeBreakdownChart.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/DutyTypeBreakdownChart.test.tsx
git commit -m "test: add coverage for DutyTypeBreakdownChart's empty state and data filtering"
```

---

### Task 7: Relocate `BugReportDetailModal`, add attachment-thumbnail fallback UI

**Files:**
- Move: `frontend/src/pages/admin/BugReportDetailModal.tsx` → `frontend/src/components/BugReportDetailModal.tsx`
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx` (import path)
- Modify: `frontend/src/pages/MyRequestsPage.tsx` (import path)
- Modify: `frontend/src/components/BugReportDetailModal.tsx` (post-move) — `AttachmentThumbnail` fallback UI
- Test: none pre-existing for this component; add a small one for the fallback UI

**Interfaces:**
- No prop changes to `BugReportDetailModal` itself — only its file location and one internal sub-component's render output on error.

- [ ] **Step 1: Move the file**

```bash
git mv frontend/src/pages/admin/BugReportDetailModal.tsx frontend/src/components/BugReportDetailModal.tsx
```

- [ ] **Step 2: Update both import sites**

In `frontend/src/pages/admin/BugReportsContent.tsx`:
```tsx
// BEFORE
import BugReportDetailModal from "./BugReportDetailModal";
// AFTER
import BugReportDetailModal from "../../components/BugReportDetailModal";
```

In `frontend/src/pages/MyRequestsPage.tsx`:
```tsx
// BEFORE
import BugReportDetailModal from "./admin/BugReportDetailModal";
// AFTER
import BugReportDetailModal from "../components/BugReportDetailModal";
```

(Confirm the exact relative path depth from each file's real location — adjust `../` count if these files aren't at the depth assumed here.)

- [ ] **Step 3: Write the failing test for the fallback UI**

Create `frontend/src/components/BugReportDetailModal.test.tsx` if none exists (check first), or add to it if it does:

```tsx
it("shows a fallback icon when the attachment thumbnail fails to load", async () => {
  // Mock the api client's GET for the attachment download URL to reject.
  // Match this codebase's existing mocking convention for axios-based `api`
  // calls (check a sibling test, e.g. one testing an upload/download flow,
  // for the exact vi.mock shape used elsewhere) before finalizing this test.
  ...
  expect(await screen.findByTestId("attachment-thumbnail-fallback")).toBeInTheDocument();
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/BugReportDetailModal.test.tsx`
Expected: FAIL — no fallback UI exists yet

- [ ] **Step 5: Add the fallback UI**

In the (now-moved) `BugReportDetailModal.tsx`'s `AttachmentThumbnail` component, replace the silent `.catch(() => {})` with a small error-state:

```tsx
const [url, setUrl] = useState<string | null>(null);
const [failed, setFailed] = useState(false);

useEffect(() => {
  let objectUrl: string | null = null;
  let cancelled = false;
  setFailed(false);
  api
    .get(bugReportCommentAttachmentDownloadUrl(reportId, commentId, attachmentId), { responseType: "blob" })
    .then((res) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(res.data as Blob);
      setUrl(objectUrl);
    })
    .catch(() => {
      if (!cancelled) setFailed(true);
    });
  return () => {
    cancelled = true;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  };
}, [reportId, commentId, attachmentId]);

if (failed) {
  return (
    <div
      data-testid="attachment-thumbnail-fallback"
      className="w-16 h-16 flex items-center justify-center rounded border border-dashed border-gray-300 dark:border-gray-600 text-gray-400 text-xs"
      title={fileName}
    >
      ⚠
    </div>
  );
}
if (!url) return null;
```

(Preserve whatever the existing successful-render JSX looks like below this point — only the failure branch and the `failed` state are new.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/BugReportDetailModal.test.tsx`
Expected: PASS

- [ ] **Step 7: Run typecheck and the broader test suite for regressions from the file move**

Run: `cd frontend && npm run typecheck && npx vitest run`
Expected: no errors, no regressions from the import path changes

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/BugReportDetailModal.tsx frontend/src/components/BugReportDetailModal.test.tsx frontend/src/pages/admin/BugReportDetailModal.tsx frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/MyRequestsPage.tsx
git commit -m "refactor: move BugReportDetailModal to components/ (used by two non-nested pages); add attachment thumbnail failure fallback"
```

---

### Task 8: Add a retry affordance after a failed attachment upload

**Files:**
- Modify: `frontend/src/components/BugReportDetailModal.tsx` (post-move from Task 7 — if Task 7 hasn't landed yet when this task runs, use the pre-move path `frontend/src/pages/admin/BugReportDetailModal.tsx` and adjust)
- Test: extend `BugReportDetailModal.test.tsx`

**Interfaces:**
- Produces: after a comment posts successfully but its attachment upload fails, the UI keeps a reference to the failed file and offers a "נסה שוב" (try again) button that re-attempts only the upload (not a new comment).

- [ ] **Step 1: Write the failing test**

```tsx
it("offers a retry button when the attachment upload fails, and retrying succeeds", async () => {
  // Mock createComment to succeed and uploadCommentAttachment to fail once
  // then succeed on retry. Match this file's/sibling files' existing
  // API-mocking convention.
  ...
  // After the initial send: expect an attachment-upload-failed message and a
  // retry button.
  expect(await screen.findByText(/attachment_upload_failed/i)).toBeInTheDocument();
  const retryButton = screen.getByRole("button", { name: /נסה שוב/ });
  fireEvent.click(retryButton);
  // After retry succeeds: the failure message should clear.
  await waitFor(() => expect(screen.queryByText(/attachment_upload_failed/i)).not.toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/BugReportDetailModal.test.tsx -t "retry"`
Expected: FAIL — no retry button exists

- [ ] **Step 3: Implement retry**

Read the current `handleSend` function in full first. Add state to retain the failed upload's target comment and file, and a retry handler:

```tsx
const [failedUpload, setFailedUpload] = useState<{ commentId: string; file: File } | null>(null);

async function handleSend() {
  if (!text.trim() || sending) return;
  setError(null);
  setAttachmentError(null);
  setFailedUpload(null);
  setSending(true);
  const pendingFile = file;
  try {
    const comment = await createComment(reportId, text.trim());
    setText("");
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });

    if (pendingFile) {
      try {
        await uploadCommentAttachment(reportId, comment.id, pendingFile);
        await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });
      } catch {
        setAttachmentError(t("bug_reports.attachment_upload_failed"));
        setFailedUpload({ commentId: comment.id, file: pendingFile });
      }
    }
  } catch (err: unknown) {
    setError(translateApiError(err, t));
  } finally {
    setSending(false);
  }
}

async function handleRetryAttachment() {
  if (!failedUpload) return;
  try {
    await uploadCommentAttachment(reportId, failedUpload.commentId, failedUpload.file);
    await qc.invalidateQueries({ queryKey: queryKeys.bugReportComments(reportId) });
    setAttachmentError(null);
    setFailedUpload(null);
  } catch {
    setAttachmentError(t("bug_reports.attachment_upload_failed"));
  }
}
```

Render the retry button next to the `attachmentError` message:

```tsx
{attachmentError && (
  <p className="text-amber-600 text-xs mt-1 flex items-center gap-2">
    {attachmentError}
    {failedUpload && (
      <button type="button" onClick={handleRetryAttachment} className="underline">
        נסה שוב
      </button>
    )}
  </p>
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/BugReportDetailModal.test.tsx`
Expected: PASS (all tests including new ones)

- [ ] **Step 5: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BugReportDetailModal.tsx frontend/src/components/BugReportDetailModal.test.tsx
git commit -m "feat: offer a retry button when a comment's attachment fails to upload"
```

---

### Task 9: Migrate `BugReportsContent.tsx`'s table onto `DataTable` (sortable + filterable), dedupe status/severity labels to i18n

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx`
- Test: extend `frontend/src/pages/admin/BugReportsContent.test.tsx`

**Interfaces:**
- Consumes: `DataTable<T>` from `frontend/src/components/DataTable.tsx` — `ColDef<T>` shape `{id, header, cell, sortValue?, filterValue?, columnFilter?, customColumnFilter?, minWidth?, exportValue?, sortDescFirst?}`, and its `expandable` prop (confirmed by investigation to closely match this file's existing hand-rolled expand-row behavior).
- Produces: the existing server-side severity/status filter `<select>`s stay as-is (they filter the full server-side dataset across pages); `DataTable` additionally provides client-side sorting on the current page's columns (date, reporter, severity, status, description) and a text-based column filter on reporter name and description (client-side, scoped to the current page's 20 rows — this is an additive convenience on top of, not a replacement for, the existing server-side severity/status filters).

- [ ] **Step 1: Read the full current file and `DataTable`'s real interface**

Read `frontend/src/pages/admin/BugReportsContent.tsx` in full (it's ~353 lines) and `frontend/src/components/DataTable.tsx`'s `ColDef<T>`/`expandable` prop shape in full, to confirm exact current structure before making changes — line numbers may have shifted from prior tasks in this same plan (e.g. Task 7's file move touches this file's imports).

- [ ] **Step 2: Replace `STATUS_LABELS`/`SEVERITY_LABELS` with the existing i18n keys**

```tsx
// BEFORE
const SEVERITY_LABELS: Record<BugReportSeverity, string> = { low: "נמוכה", medium: "בינונית", high: "גבוהה" };
const STATUS_LABELS: Record<BugReportStatus, string> = {
  open: "פתוח", in_progress: "בטיפול", resolved: "טופל", wont_fix: "לא יטופל",
};
```

```tsx
// AFTER — use t("bug_reports.severity_<x>") / t("bug_reports.status_<x>") at each call site instead of these
// constants object lookups. Keep SEVERITY_COLORS as-is (no i18n equivalent needed for Tailwind classes).
```

Find every call site that referenced `SEVERITY_LABELS[...]`/`STATUS_LABELS[...]` (filter dropdown options, per-row cells) and replace with `t(\`bug_reports.severity_${severity}\`)` / `t(\`bug_reports.status_${status}\`)`, matching the exact pattern already used in `MyRequestsPage.tsx` (`bugReportSeverityLabel`/`bugReportStatusLabel` helper functions, lines ~173-174 — consider extracting the same two small helper functions into this file too, for symmetry).

- [ ] **Step 3: Write the failing test for DataTable migration**

Read `BugReportsContent.test.tsx`'s existing tests first (there should be at least the row-click-expansion test from a prior task). Add or adapt a test confirming sorting works, e.g.:

```tsx
it("sorts rows by date when the date column header is clicked", async () => {
  // Render with 2+ mocked bug reports with different created_at values,
  // click the date column header, assert row order changes.
  ...
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/BugReportsContent.test.tsx -t "sorts rows"`
Expected: FAIL — no sortable column header exists yet (still a hand-rolled table)

- [ ] **Step 5: Replace the hand-rolled `<table>` with `DataTable`**

Read the full current `<table>...</table>` block (previously at lines ~214-330, confirm current lines) and the existing `expandedId`/`toggleExpand` state. Replace with:

```tsx
<DataTable<BugReportSummary>
  columns={[
    {
      id: "created_at",
      header: "תאריך",
      cell: (r) => new Date(r.created_at).toLocaleString("he-IL"),
      sortValue: (r) => r.created_at,
    },
    {
      id: "reporter",
      header: "מדווח",
      cell: (r) => (r.user_snapshot?.full_name as string) ?? "—",
      sortValue: (r) => (r.user_snapshot?.full_name as string) ?? "",
      filterValue: (r) => (r.user_snapshot?.full_name as string) ?? "",
    },
    {
      id: "severity",
      header: "חומרה",
      cell: (r) => (
        <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[r.severity]}`}>
          {t(`bug_reports.severity_${r.severity}`)}
        </span>
      ),
      sortValue: (r) => r.severity,
    },
    {
      id: "status",
      header: "סטטוס",
      cell: (r) => (
        <select
          value={r.status}
          onChange={(e) => handleStatusChange(r.id, e.target.value as BugReportStatus)}
          onClick={(e) => e.stopPropagation()}
          className="border rounded px-1 py-0.5 text-xs dark:bg-gray-700 dark:border-gray-600"
          data-testid={`bug-report-status-${r.id}`}
        >
          <option value="open">{t("bug_reports.status_open")}</option>
          <option value="in_progress">{t("bug_reports.status_in_progress")}</option>
          <option value="resolved">{t("bug_reports.status_resolved")}</option>
          <option value="wont_fix">{t("bug_reports.status_wont_fix")}</option>
        </select>
      ),
      sortValue: (r) => r.status,
    },
    {
      id: "description",
      header: "תיאור",
      cell: (r) => <span className="truncate max-w-xs block">{r.description}</span>,
      filterValue: (r) => r.description,
    },
  ]}
  data={items}
  expandable={{
    content: (r) => (
      <div className="p-3">
        {/* move the existing expanded-detail JSX here verbatim — screenshot,
            user snapshot, nav history, audit snapshot, "הצג JSON" button,
            and the "תגובות" button + BugReportDetailModal wiring */}
      </div>
    ),
  }}
/>
```

(This is illustrative of the column shape, not a guess at every field name — confirm `BugReportSummary`'s real field names, e.g. `created_at`/`user_snapshot`/`description`, against the actual TS type in `frontend/src/api/bugReports.ts` before finalizing. Keep `handleStatusChange` and the status `<select>`'s `data-testid` pattern exactly as they are today, since Task 10 replaces this cell with icon buttons on top of this same structure.)

Note: `DataTable`'s row-click-to-expand affordance is via a dedicated toggle button/column, not click-anywhere-on-the-row like the current hand-rolled table. This is an intentional, disclosed behavior change — the toggle is still one click, just via a specific control rather than the whole row. If `DataTable`'s `expandable` prop doesn't already support this out of the box, read its actual implementation first and adapt to whatever mechanism it provides rather than inventing a parallel one.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/admin/BugReportsContent.test.tsx`
Expected: PASS (all tests including the new sorting test)

- [ ] **Step 7: Run typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 8: Manually verify in the running app**

Start `.\dev.ps1`, log in as admin, open bug reports, confirm: clicking a column header sorts the current page's rows; the reporter/description columns have a working filter; the existing severity/status server-side filters and pagination still work; expanding a row still shows the full detail (screenshot, JSON, comments button) correctly.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/admin/BugReportsContent.test.tsx
git commit -m "feat: migrate bug reports table to DataTable for sortable and filterable columns"
```

---

### Task 10: Status icon buttons replacing the per-row `<select>`, with row background color by status

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx` (status cell from Task 9, plus `DataTable`'s row rendering if it needs a new capability)
- Modify: `frontend/src/components/DataTable.tsx` (only if it doesn't already support a per-row className/style — confirm first)
- Test: extend `frontend/src/pages/admin/BugReportsContent.test.tsx`

**Interfaces:**
- Produces: 4 small icon buttons per row (one per status: open, in_progress, resolved, wont_fix), the active one visually highlighted; clicking a different one calls the existing `handleStatusChange`. The row's background color reflects its current status.

- [ ] **Step 1: Check whether `DataTable` supports a per-row className/style**

Read `frontend/src/components/DataTable.tsx`'s row-rendering code (the `<tr>`/`<TableRow>` mapping) in full. If there's no existing `rowClassName`-style prop, add one additively:

```tsx
// Add to DataTable's props interface:
rowClassName?: (row: T) => string;

// Apply it to the row element, merged with existing row classes:
className={`${existingRowClasses} ${rowClassName ? rowClassName(row) : ""}`}
```

(Read the exact current row `className` construction first — this must be additive, not replace existing hover/border/expand-state classes.)

- [ ] **Step 2: Write the failing tests**

```tsx
it("renders one icon button per status, highlighting the current status", () => {
  // Render with a report whose status is "in_progress".
  // Assert 4 buttons exist (one per status) and the in_progress one has an
  // "active" visual marker (e.g. a distinct class or aria-pressed="true").
  ...
});

it("clicking a status icon button changes the report's status", () => {
  // Click the "resolved" icon button, assert handleStatusChange (or the
  // underlying API call) was invoked with the new status.
  ...
});

it("colors the row background according to the report's status", () => {
  // Assert the row element has a status-specific background class present
  // for at least two different status values.
  ...
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/admin/BugReportsContent.test.tsx -t "status icon"`
Expected: FAIL — still the old `<select>`

- [ ] **Step 4: Define status → icon/color mapping and implement**

Near the top of the file, alongside `SEVERITY_COLORS`:

```tsx
const STATUS_ICONS: Record<BugReportStatus, string> = {
  open: "🔴",
  in_progress: "🟡",
  resolved: "🟢",
  wont_fix: "⚪",
};

const STATUS_ROW_BG: Record<BugReportStatus, string> = {
  open: "bg-red-50 dark:bg-red-950/30",
  in_progress: "bg-yellow-50 dark:bg-yellow-950/30",
  resolved: "bg-green-50 dark:bg-green-950/30",
  wont_fix: "bg-gray-50 dark:bg-gray-800/50",
};

const STATUS_ORDER: BugReportStatus[] = ["open", "in_progress", "resolved", "wont_fix"];
```

Replace the status `<select>` cell (from Task 9) with:

```tsx
{
  id: "status",
  header: "סטטוס",
  cell: (r) => (
    <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
      {STATUS_ORDER.map((s) => (
        <button
          key={s}
          type="button"
          aria-pressed={r.status === s}
          title={t(`bug_reports.status_${s}`)}
          onClick={() => handleStatusChange(r.id, s)}
          className={`w-7 h-7 flex items-center justify-center rounded text-sm ${
            r.status === s ? "ring-2 ring-indigo-500" : "opacity-40 hover:opacity-70"
          }`}
          data-testid={`bug-report-status-${s}-${r.id}`}
        >
          {STATUS_ICONS[s]}
        </button>
      ))}
    </div>
  ),
  sortValue: (r) => r.status,
},
```

Wire `rowClassName` (from Step 1) into the `<DataTable>` call from Task 9:

```tsx
rowClassName={(r) => STATUS_ROW_BG[r.status]}
```

(Emoji icons are a placeholder for a quick, dependency-free visual distinction — if this codebase already has an icon library/set in use elsewhere for small status glyphs, check for one first and use it instead of raw emoji for visual consistency; adjust `STATUS_ICONS` accordingly if so.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/admin/BugReportsContent.test.tsx`
Expected: PASS (all tests including new ones)

- [ ] **Step 6: Run typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 7: Manually verify in the running app**

Start `.\dev.ps1`, open bug reports as admin, confirm each row's background reflects its status color, the 4 icon buttons render per row with the current status highlighted, and clicking a different icon updates both the status and the row's background color immediately.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/admin/BugReportsContent.test.tsx frontend/src/components/DataTable.tsx
git commit -m "feat: replace bug report status dropdown with icon buttons and color rows by status"
```

---

## Self-Review Notes

- All 14 originally-logged minor findings are covered: 1→Task 1, 2→Task 2, 3→already resolved (documented in Global Constraints), 4→Task 5, 5→Task 2, 6→Task 2, 7→Task 3, 8→Task 4, 9→already resolved (documented in Global Constraints), 10→Task 6, 11→Task 7, 12→Task 9, 13→Task 7, 14→Task 8.
- Both new features (status icon buttons + row coloring; filterable/sortable table) are covered by Tasks 9-10, deliberately sequenced so the table structure lands first and the status-cell rework builds on top of it rather than both being rewritten simultaneously.
- Task 9/10 explicitly call out one real behavior change (row-click-to-expand becoming a dedicated toggle click under `DataTable`) rather than silently absorbing it — this is disclosed for the implementer/reviewer to confirm is acceptable, not hidden.
- No placeholders remain; a few exact field names/paths are marked "confirm by reading the file first" where prior investigation summarized but didn't quote every line — intentional precision-over-guessing given multiple earlier tasks in this same plan touch the same files sequentially and could shift line numbers.
