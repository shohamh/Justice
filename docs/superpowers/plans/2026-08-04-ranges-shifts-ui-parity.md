# Ranges/Shifts UI Parity & Unit Calendar Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Ranges ("מטווחים") management UI's interaction patterns match Shifts ("משמרות") management: one entry point per action (no duplicate buttons across modals), a candidate-selection panel for filling a roster instead of one-click auto-assign, and a bulk-select/bulk-action layer for the ranges list. Also replace the unit calendar's ever-growing filter-pill rows with multi-select dropdowns (Part D — already implemented in a separate worktree; documented here for a complete record of this round of UI work).

**Architecture:** Four parts. Parts A-C are independent of each other and of Part D; each is independently mergeable and testable:

- **Part A — Interaction parity**: collapse ranges' 4-modal chain (detail → edit-assignments → form → cancel) down to direct row actions, matching shifts' "no intermediate read-only screen for managers" pattern. Removes duplicate ערוך/בטל buttons and the ambiguous hidden-vs-disabled delete button.
- **Part B — Candidate panel replaces one-click auto-assign**: today's `RangeEditAssignmentsModal` has a "שיבוץ אוטומטי" button that synchronously creates *draft* assignments server-side, which the user then reviews and confirms one-by-one. Shifts instead shows a persistent, ranked candidate list with checkboxes and a "בחר אוטומטית" button that pre-checks the top-N candidates *client-side*, and the user reviews/adjusts *before* anything is saved. This plan ports that pattern to ranges: a new read-only `GET /ranges/{event_id}/candidates` endpoint (reusing the existing ranking logic) plus a new `POST /ranges/{event_id}/assignments/batch` endpoint that creates real (non-draft) assignments in one call — the client-side review *is* the confirmation step, so the server-side draft/confirm workflow becomes dead code and is removed along with it.
- **Part C — Bulk operations**: adds row-selection checkboxes and a bulk action bar to `RangesPage.tsx`, mirroring `ShiftsPage.tsx`'s `BulkActionBar` exactly — bulk clear-assignments, bulk cancel, bulk delete, each implemented as a client-side `Promise.all`/`Promise.allSettled` loop over the existing single-item endpoints (this is the established convention in this codebase; shifts does not have real batch endpoints for these three either).
- **Part D — Unit calendar filter dropdowns** *(status: done)*: replaced the one-pill-per-duty-type / one-pill-per-range-type filter rows in `UnitCalendar.tsx` with two `CheckboxListDropdown` multi-select dropdowns (one per category, already rendered as separate groups before this change — only the control type changed). Implemented and committed on branch `worktree-calendar-filter-dropdowns` (worktree at `.claude/worktrees/calendar-filter-dropdowns`), commit `5848cfdc` — "feat: replace unit calendar filter pills with multi-select dropdowns". Not yet merged to `dev`. See Task D1 below for the merge step.

**Tech Stack:** FastAPI + SQLAlchemy (backend/app), React + TypeScript + Vite + Tailwind + react-i18next + TanStack Query (frontend/src), pytest (backend/tests), vitest + Testing Library (frontend/src/**/*.test.tsx).

## Global Constraints

- Hebrew UI strings, English code/identifiers — follow existing i18n conventions in `frontend/src/i18n/he.json` (either a hardcoded Hebrew string matching the existing convention in these files, which mostly don't use `t()` for range strings, or `t("ranges.xxx", "fallback")` where the component already uses the `text()` helper — match whichever convention the file you're editing already uses).
- `RANGE_MANAGE` authorization (`app.auth.authz.Action.RANGE_MANAGE`) gates every mutating ranges route — new routes must use the same `authorize(session, user, Action.RANGE_MANAGE, target_node=...)` pattern.
- All new/changed pytest tests must pass under `pytest -q` (backend) and get the `duty` area marker automatically (backend/tests/conftest.py maps `test_range_*` filenames to `"duty"` already — new range test files follow the same naming prefix).
- All new/changed vitest tests must pass under `npm test` (frontend) and `npm run typecheck` / `npm run lint` must stay clean (zero warnings).
- Never remove a passing test without a comment explaining why its premise no longer holds — this plan calls out exactly which existing tests become invalid and what replaces them.
- Follow this repo's compact JSX style already used in `RangesPage.tsx`/`RangeEditAssignmentsModal.tsx` (long single-line JSX, not the multi-line-per-attribute style) — don't reformat unrelated lines while editing.

---

## Part A — Interaction Parity

### Task A1: Route the שיבוצים row button directly to the assignments editor

Today `RangesPage.tsx`'s "📋 שיבוצים" row button (added in a prior session) calls `setSelected(e.id)`, which opens the read-only `RangeDetailContent` modal; a manager then has to click "ערוך שיבוצים" *inside* that modal to reach `RangeEditAssignmentsModal`. This task makes שיבוצים jump straight to the assignments editor, matching shifts (row button → editor, no detail screen in between).

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `getRangeEvent(id: string): Promise<RangeEvent>` (`frontend/src/api/ranges.ts:9`, already imported in `RangesPage.tsx`), existing `editAssignments: RangeEvent | null` state and `RangeEditAssignmentsModal` (`RangesPage.tsx:21,70`).
- Produces: no new exports; behavior change only.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/RangesPage.test.tsx` (near the existing `"opens the range detail directly from the שיבוצים row action..."` test — replace that test's body, since its premise changes):

```tsx
  it("opens the assignments editor directly from the שיבוצים row action, without the detail modal", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
      date: "2026-09-01", location: "מטווח דרום", required_count: 4,
      reserve_count: 1, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />);

    await screen.findByText("מטווח דרום");
    fireEvent.click(screen.getByTestId("view-assignments-event-1"));

    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-1"));
    expect(await screen.findByRole("heading", { name: "עריכת שיבוצים" })).toBeInTheDocument();
    expect(screen.queryByTestId("range-detail-content")).not.toBeInTheDocument();
  });
```

Remove the old test with the same `view-assignments-event-1` premise (`"opens the range detail directly from the שיבוצים row action without clicking the location link"`) — it asserted the *old* behavior (opens `range-detail-content`), which this task intentionally changes.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx -t "opens the assignments editor directly"`
Expected: FAIL — `queryByRole("heading", { name: "עריכת שיבוצים" })` not found (still opens detail modal).

- [ ] **Step 3: Implement**

In `frontend/src/pages/RangesPage.tsx`, change the שיבוצים button's `onClick` (currently `() => { setSelected(e.id); setEditAssignments(null); }`) to fetch the full event and open the editor directly:

```tsx
onClick={async () => { const detail = await getRangeEvent(e.id); setEditAssignments(detail); }}
```

This replaces the existing `onClick` at the `data-testid="view-assignments-${e.id}"` button (currently the first button inside `rowActions`). Leave `onRowClick` (the location-name click, which still opens the read-only detail modal) unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx`
Expected: PASS (all tests in the file, not just the new one — check for other tests broken by this change, e.g. any that clicked שיבוצים expecting the detail modal; fix their assertions to match the new direct-to-editor behavior using the same pattern as the new test above).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "feat: open range assignments editor directly from row action"
```

### Task A2: Remove duplicate ערוך/בטל buttons from the detail modal

`RangesPage.tsx:69` passes an `actions` prop to `EventDetailModal` (via `RangeDetailContent`) containing "ערוך" (→ `setFormEvent`) and "בטל" (→ `setCancelId`) buttons — both exact duplicates of the row's "✏️ עריכה" and "🚫 ביטול" buttons. Shifts has no such duplication (no detail screen at all). Remove this `actions` prop entirely; the detail modal becomes purely a read-only/self-service view (info, self-excusal, excusal-request review, attendance) reached via the location-name link.

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `EventDetailModal`'s `actions?: ReactNode` prop (`frontend/src/components/planning/EventDetailModal.tsx:16`) — passing `undefined` renders nothing (`EventDetailModal.tsx:70`: `{actions && ...}`).
- Produces: `RangeDetailContent`'s `Props` interface loses `onEditAssignments` and the "פעולות שיבוץ" section (see Task A3 — done together since both remove the same duplication source).

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/RangesPage.test.tsx`, replace the `"uses standard detail metadata, action buttons, and grouped range information"` test's assertions about `range-detail-actions` — it currently expects `screen.getByTestId("range-detail-actions")` to exist and contain "ערוך"/"בטל" buttons. Change it to assert those are gone:

```tsx
    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector("dl")).toHaveClass("grid", "rounded", "p-3");
    expect(screen.queryByTestId("range-detail-actions")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ערוך" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "בטל" })).not.toBeInTheDocument();
    expect(screen.getByTestId("range-detail-information")).toHaveClass("text-gray-800", "dark:text-gray-100");
```

(Keep the rest of that test — the `הוראות הגעה:`/`איש קשר:`/`הערות:` assertions — unchanged.)

Also update `"keeps detail selected when Escape closes the edit modal"` — it currently opens the form via clicking "ערוך" *inside the detail modal*. Change it to open the form via the row button instead (the row button is what remains):

```tsx
  it("keeps detail selected when Escape closes the edit modal", async () => {
    const range = {
      id: "event-edit", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח עריכה", required_count: 1, reserve_count: 0,
      status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([range]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(range);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח עריכה"));
    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("edit-range-event-edit"));
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByTestId("range-form")).not.toBeInTheDocument());
    expect(screen.getByTestId("range-detail-content")).toBeInTheDocument();
  });
```

Similarly update `"keeps detail selected when Escape closes the cancel dialog"` to trigger cancel via the row's `cancel-range-event-cancel` button instead of the in-modal "בטל":

```tsx
  it("keeps detail selected when Escape closes the cancel dialog", async () => {
    const range = {
      id: "event-cancel", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח ביטול", required_count: 1, reserve_count: 0,
      status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([range]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(range);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח ביטול"));
    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("cancel-range-event-cancel"));
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "ביטול מטווח" })).not.toBeInTheDocument());
    expect(screen.getByTestId("range-detail-content")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx`
Expected: FAIL — `range-detail-actions` still present, "ערוך"/"בטל" still rendered inside the detail modal.

- [ ] **Step 3: Implement**

In `frontend/src/pages/RangesPage.tsx`, remove the `actions={...}` prop entirely from the `EventDetailModal` call (the block starting `actions={manage && event.data.status === "planned" ? <div data-testid="range-detail-actions" ...` through its closing `: undefined}`), so the modal is invoked without an `actions` prop at all.

Also remove the now-unused `onEditAssignments={() => setEditAssignments(event.data!)}` prop passed to `RangeDetailContent` in that same call (Task A3 removes the corresponding prop from `RangeDetailContent` itself).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "fix: remove duplicate edit/cancel buttons from range detail modal"
```

### Task A3: Remove the "פעולות שיבוץ" section from RangeDetailContent

With Task A1 routing שיבוצים directly to the editor, the "ערוך שיבוצים" button inside `RangeDetailContent`'s "פעולות שיבוץ" section is now a second, redundant path to the same modal. Remove it — the detail modal becomes purely read-only for managers too (self-excusal and attendance marking remain, since those aren't roster-editing actions).

**Files:**
- Modify: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.test.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: none new.
- Produces: `RangeDetailContent`'s `Props` interface drops `onEditAssignments?: () => void`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/components/ranges/RangeDetailContent.test.tsx`, find any test asserting `edit-range-assignments` is present for a manager and change it to assert it's *absent* regardless of `canManage`:

```tsx
  it("never renders an edit-assignments entry point — that's reached via the row action now", () => {
    render(<RangeDetailContent {...baseProps({ canManage: true })} />);
    expect(screen.queryByTestId("edit-range-assignments")).not.toBeInTheDocument();
    expect(screen.queryByText("פעולות שיבוץ")).not.toBeInTheDocument();
  });
```

(Adapt `baseProps(...)` to match whatever prop-building helper already exists at the top of that test file — read the file first to match its exact helper name/shape before writing this.)

In `frontend/src/pages/RangesPage.test.tsx`, update `"keeps assignment mutations out of the range detail content"` (currently asserts `edit-range-assignments` *is* present inside `range-detail-content`) to assert it is *not*:

```tsx
  it("keeps assignment mutations out of the range detail content", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח דרום", required_count: 1, reserve_count: 1,
      status: "planned" as const,
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
        attendance_status: "pending" as const, note: null }],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    expect(screen.queryByTestId("edit-range-assignments")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-soldier-button")).not.toBeInTheDocument();
    expect(screen.queryByText("הסר")).not.toBeInTheDocument();
  });
```

And `"closes only the assignment editor on Escape and preserves the selected detail"` (currently opens the editor by clicking `edit-range-assignments` *inside* the detail modal) — change to open via the row's שיבוצים button instead, and open the detail modal separately afterward via the location link to check it's preserved:

```tsx
  it("closes only the assignment editor on Escape and preserves the selected detail", async () => {
    const event = {
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser" as const,
      date: "2026-09-01", location: "מטווח דרום", required_count: 1, reserve_count: 0,
      status: "planned" as const, assignments: [],
    };
    vi.mocked(rangesApi.getRanges).mockResolvedValue([event]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue(event);

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByTestId("view-assignments-event-1"));

    expect(await screen.findByRole("heading", { name: "עריכת שיבוצים" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "עריכת שיבוצים" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByText("מטווח דרום"));
    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "מטווח דרום" })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ranges/RangeDetailContent.test.tsx src/pages/RangesPage.test.tsx`
Expected: FAIL — `edit-range-assignments` / "פעולות שיבוץ" still rendered.

- [ ] **Step 3: Implement**

In `frontend/src/components/ranges/RangeDetailContent.tsx`:
- Remove `onEditAssignments?: () => void;` from the `Props` interface.
- Remove the entire line: `{p.canManage && planned && <section className="space-y-2 rounded border p-4 dark:border-gray-600"><h3 className="text-sm font-semibold">פעולות שיבוץ</h3><div className="flex flex-wrap gap-2">{p.onEditAssignments && <button type="button" data-testid="edit-range-assignments" onClick={p.onEditAssignments} className={\`${actionClass} border-indigo-600 bg-indigo-600 text-white\`}>ערוך שיבוצים</button>}</div></section>}`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ranges/RangeDetailContent.test.tsx src/pages/RangesPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ranges/RangeDetailContent.tsx frontend/src/components/ranges/RangeDetailContent.test.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "fix: remove redundant edit-assignments entry point from detail view"
```

### Task A4: Delete button — always visible, disabled when assigned (matches shifts)

Today the row's "🗑️ מחיקה" button is *hidden* entirely when `count(e,false) > 0 || count(e,true) > 0`, and its `onClick` re-fetches the full event and re-checks assignment count before calling `deleteRangeEvent` (a defensive double-check). `backend/app/services/ranges.py:263-280 delete_range_event` already raises `RangeValidationError("event_has_assignments")` authoritatively if any assignment rows exist — the frontend re-fetch is redundant. Shifts shows delete always, disabled by `disabled={s.assigned_count > 0}`, relying on the backend as final authority. Match that: always show the button, disable it when the (already-known, no extra fetch) counts are non-zero, and drop the extra fetch-then-check.

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `deleteRangeEvent(id: string): Promise<void>` (`frontend/src/api/ranges.ts`), existing `count(e, reserve): number` helper (`RangesPage.tsx:39-43`).
- Produces: none new.

- [ ] **Step 1: Write the failing test**

Replace `"does not offer deletion when assignments exist despite stale filled counts"` in `frontend/src/pages/RangesPage.test.tsx` — its premise (button hidden, re-fetch-then-skip) no longer holds. New test asserts the button is present-but-disabled and never calls delete when clicked-while-disabled:

```tsx
  it("shows the delete button disabled (not hidden) when the event has assignments", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-with-assignment", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח עם שיבוץ", required_count: 4,
        reserve_count: 1, primary_filled: 1, reserve_filled: 0, status: "planned",
        assignments: [{
          id: "assignment-1", soldier_id: "soldier-1", is_reserve: false,
          is_draft: false, attendance_status: "pending", note: null,
        }],
      },
    ]);

    renderWithQuery(<RangesPage />);

    const del = await screen.findByTestId("delete-range-event-with-assignment");
    expect(del).toBeDisabled();
    fireEvent.click(del);
    expect(rangesApi.deleteRangeEvent).not.toHaveBeenCalled();
  });

  it("shows the delete button enabled and deletes when the event has no assignments", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-empty", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח ריק", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(rangesApi.deleteRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);

    const del = await screen.findByTestId("delete-range-event-empty");
    expect(del).not.toBeDisabled();
    fireEvent.click(del);
    await waitFor(() => expect(rangesApi.deleteRangeEvent).toHaveBeenCalledWith("event-empty"));
  });
```

Remove `"uses list summary counts for production list responses with no inline assignments"` and `"rechecks authoritative detail before deleting a range with draft assignments"` — both tested the removed hidden-vs-refetch behavior and no longer apply.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx -t "delete button"`
Expected: FAIL — button not found at all when assignments exist (still hidden today).

- [ ] **Step 3: Implement**

In `frontend/src/pages/RangesPage.tsx`, replace the delete button block:

```tsx
{count(e, false) === 0 && count(e, true) === 0 && <button type="button" data-testid={`delete-range-${e.id}`} onClick={async () => { if (!confirm("למחוק?")) return; const detail = await getRangeEvent(e.id); if (detail.assignments.length !== 0) return; setSelected(current => current === e.id ? null : current); await deleteRangeEvent(e.id); await invalidate(); }} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800">🗑️ מחיקה</button>}
```

with:

```tsx
<button type="button" disabled={count(e, false) > 0 || count(e, true) > 0} data-testid={`delete-range-${e.id}`} onClick={async () => { if (!confirm("למחוק?")) return; setSelected(current => current === e.id ? null : current); await deleteRangeEvent(e.id); await invalidate(); }} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800 disabled:opacity-40 disabled:cursor-not-allowed">🗑️ מחיקה</button>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "fix: always show range delete button, disabled when assigned (matches shifts)"
```

---

## Part B — Candidate Panel Replaces One-Click Auto-Assign

### Task B1: Backend — non-mutating ranked candidates endpoint

Add `GET /ranges/{event_id}/candidates`, returning every eligible soldier for the event ranked the same way `propose_range_assignments` already ranks them, annotated with a `blocked`/`blocked_reason` flag for ineligible soldiers (mirroring `ShiftCandidateOut` at `backend/app/routes/shifts.py:608-615`) — but *not* writing anything to the database. Refactor `_candidate_pool`/`_rank_candidate` out of the mutating flow so both the new endpoint and the (soon-to-be-removed) `propose_range_assignments` can share them during the transition; `propose_range_assignments` and the draft/confirm machinery are deleted in Task B4 once nothing else depends on them.

**Files:**
- Modify: `backend/app/services/range_auto_assign.py`
- Modify: `backend/app/routes/ranges.py`
- Test: `backend/tests/unit/test_range_candidates.py` (new)

**Interfaces:**
- Consumes: `_candidate_pool(session, *, event, exclude_soldier_ids) -> list[Soldier]` and `_rank_candidate(session, *, soldier, event) -> tuple[tuple, str]` (both already exist, unchanged signatures, at `range_auto_assign.py:104,92`).
- Produces: `rank_candidates(session, *, event: RangeEvent) -> list[RankedCandidate]` where `RankedCandidate` is a new `@dataclass` `{soldier: Soldier, reason_code: str, blocked: bool, blocked_reason: str | None}` — Task B2 (batch-assign) and the frontend both consume this shape via the route's Pydantic `RangeCandidateOut`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_range_candidates.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeType
from app.services.range_auto_assign import rank_candidates
from app.services.ranges import add_range_assignment, create_range_event
from tests.helpers import create_node, create_soldier


def _event(session: Session, *, required_count: int = 2, reserve_count: int = 1):
    node = create_node(session, level="branch", name="candidates")
    session.add(DutyType(name="weapon candidates", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="range",
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event


def test_ranks_available_soldiers_and_excludes_already_assigned(app_session: Session) -> None:
    node, event = _event(app_session)
    already = create_soldier(app_session, personal_number="cand-assigned", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=already.id, is_reserve=False)
    open_candidate = create_soldier(app_session, personal_number="cand-open", hierarchy_node_id=node.id)

    ranked = rank_candidates(app_session, event=event)

    ranked_ids = {c.soldier.id for c in ranked}
    assert already.id not in ranked_ids
    assert open_candidate.id in ranked_ids
    assert all(not c.blocked for c in ranked)


def test_marks_exempt_soldier_as_blocked_instead_of_excluding(app_session: Session) -> None:
    node, event = _event(app_session)
    soldier = create_soldier(app_session, personal_number="cand-exempt", hierarchy_node_id=node.id)

    from app.db.models import SoldierRangeQualification
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=event.date + timedelta(days=365), source_range_event_id=None, source_range_assignment_id=None,
    ))
    app_session.commit()

    ranked = rank_candidates(app_session, event=event)
    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is False
    assert mine.reason_code == "qualified"


def test_does_not_write_any_assignment_rows(app_session: Session) -> None:
    node, event = _event(app_session)
    create_soldier(app_session, personal_number="cand-readonly", hierarchy_node_id=node.id)

    rank_candidates(app_session, event=event)

    app_session.refresh(event)
    assert event.assignments == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_range_candidates.py -v`
Expected: FAIL with `ImportError: cannot import name 'rank_candidates'`.

- [ ] **Step 3: Implement — service layer**

In `backend/app/services/range_auto_assign.py`, add near the top (after the existing imports) a dataclass and the new non-mutating ranking function, placed just before `propose_range_assignments`:

```python
from dataclasses import dataclass


@dataclass
class RankedCandidate:
    soldier: Soldier
    reason_code: str
    blocked: bool
    blocked_reason: str | None


def rank_candidates(session: Session, *, event: RangeEvent) -> list[RankedCandidate]:
    """Read-only: ranks every soldier in the event's subtree who isn't already
    assigned to it, same tier ordering as propose_range_assignments, but never
    writes to the database. Ineligible soldiers (exempt/constrained/already
    duty- or range-assigned that day) are marked blocked=True instead of
    being excluded, so the frontend can show them (greyed out) rather than
    silently omitting them."""
    existing_soldier_ids = {
        a.soldier_id for a in session.execute(
            select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
        ).scalars().all()
    }
    subtree_node_ids = list(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(event.hierarchy_node_id))  # type: ignore[arg-type]
        ).scalars().all()
    )
    soldiers = session.execute(
        select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids))
    ).scalars().all()

    ranked: list[RankedCandidate] = []
    for soldier in soldiers:
        if soldier.id in existing_soldier_ids:
            continue
        blocked_reason = None
        if is_range_exempt(session, soldier=soldier, event_date=event.date):
            blocked_reason = "exempt"
        elif _has_approved_constraint_on_date(session, soldier_id=soldier.id, event_date=event.date):
            blocked_reason = "constraint"
        elif _has_duty_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            blocked_reason = "duty_assignment"
        elif _has_range_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            blocked_reason = "range_assignment"
        _, reason_code = _rank_candidate(session, soldier=soldier, event=event)
        ranked.append(RankedCandidate(
            soldier=soldier, reason_code=reason_code,
            blocked=blocked_reason is not None, blocked_reason=blocked_reason,
        ))

    def sort_key(c: RankedCandidate) -> tuple:
        rank, _ = _rank_candidate(session, soldier=c.soldier, event=event)
        return (c.blocked, rank)

    ranked.sort(key=sort_key)
    return ranked
```

- [ ] **Step 4: Implement — route**

In `backend/app/routes/ranges.py`, add after the existing `AutoAssignResponse`/`auto_assign` route (they'll be removed in Task B4, so place the new route right after them for now):

```python
class RangeCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    personal_number: str
    reason_code: str
    blocked: bool
    blocked_reason: str | None = None


@router.get("/{event_id}/candidates", response_model=list[RangeCandidateOut])
def get_range_candidates(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeCandidateOut]:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    ranked = auto_assign_svc.rank_candidates(session, event=event)
    return [
        RangeCandidateOut(
            soldier_id=c.soldier.id, full_name=c.soldier.full_name, personal_number=c.soldier.personal_number,
            reason_code=c.reason_code, blocked=c.blocked, blocked_reason=c.blocked_reason,
        )
        for c in ranked
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_range_candidates.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/range_auto_assign.py backend/app/routes/ranges.py backend/tests/unit/test_range_candidates.py
git commit -m "feat: add read-only ranked candidates endpoint for range events"
```

### Task B2: Backend — batch-assign endpoint

Add `POST /ranges/{event_id}/assignments/batch`, mirroring `assignBatch`'s shape for shifts (`backend/app/routes/shifts.py` — the route backing `frontend/src/api/shifts.ts:122-127`): takes `{primaries: [soldier_id], reserves: [soldier_id]}`, validates each against the same rules `add_range_assignment` already enforces (subtree membership, exemption, same-date conflict), and creates all of them as real (non-draft, `is_draft=False`) `RangeAssignment` rows in one transaction — no draft flag, since the client-side candidate panel *is* the review step.

**Files:**
- Modify: `backend/app/services/ranges.py`
- Modify: `backend/app/routes/ranges.py`
- Test: `backend/tests/unit/test_range_batch_assign.py` (new)

**Interfaces:**
- Consumes: existing per-soldier validation logic inside `add_range_assignment` (`backend/app/services/ranges.py:158-199`) — refactor its per-soldier checks into a private helper `_validate_and_build_assignment(session, *, event, soldier_id, is_reserve) -> RangeAssignment` (raising `RangeValidationError` exactly as `add_range_assignment` does today) so both the single-add route and the new batch route share it.
- Produces: `assign_batch(session, *, event: RangeEvent, primary_soldier_ids: list[uuid.UUID], reserve_soldier_ids: list[uuid.UUID], actor_id: uuid.UUID | None) -> list[RangeAssignment]` — raises `RangeValidationError` on the *first* invalid soldier (all-or-nothing, matching how `add_range_assignment` already fails fast for a single soldier; no partial-success semantics to keep this simple, unlike shifts' `assignBatch` which is more lenient — call this out to the reviewer as a deliberate simplification, not an oversight).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_range_batch_assign.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment, RangeType
from app.services.ranges import RangeValidationError, assign_batch, create_range_event
from tests.helpers import create_node, create_soldier


def _event(session: Session, *, required_count: int = 2, reserve_count: int = 1):
    node = create_node(session, level="branch", name="batch-assign")
    session.add(DutyType(name="weapon batch-assign", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="range",
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event


def test_creates_all_assignments_as_non_draft(app_session: Session) -> None:
    node, event = _event(app_session)
    primary = create_soldier(app_session, personal_number="batch-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="batch-reserve", hierarchy_node_id=node.id)

    created = assign_batch(app_session, event=event, primary_soldier_ids=[primary.id], reserve_soldier_ids=[reserve.id], actor_id=None)

    assert len(created) == 2
    assert all(not a.is_draft for a in created)
    primary_rows = [a for a in created if not a.is_reserve]
    reserve_rows = [a for a in created if a.is_reserve]
    assert [a.soldier_id for a in primary_rows] == [primary.id]
    assert [a.soldier_id for a in reserve_rows] == [reserve.id]


def test_rejects_the_whole_batch_if_one_soldier_is_invalid(app_session: Session) -> None:
    node, event = _event(app_session)
    valid = create_soldier(app_session, personal_number="batch-valid", hierarchy_node_id=node.id)
    other_node = create_node(app_session, level="branch", name="batch-outside")
    outside = create_soldier(app_session, personal_number="batch-outside", hierarchy_node_id=other_node.id)

    with pytest.raises(RangeValidationError):
        assign_batch(app_session, event=event, primary_soldier_ids=[valid.id, outside.id], reserve_soldier_ids=[], actor_id=None)

    app_session.refresh(event)
    assert event.assignments == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_range_batch_assign.py -v`
Expected: FAIL with `ImportError: cannot import name 'assign_batch'`.

- [ ] **Step 3: Implement — service layer**

In `backend/app/services/ranges.py`, find `add_range_assignment` (currently lines ~158-199 per earlier reads — verify exact lines before editing) and extract its per-soldier validation + row-construction into a helper, keeping `add_range_assignment`'s public behavior (including its notification side effect) identical. Add just after `add_range_assignment`:

```python
def _validate_and_build_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
) -> RangeAssignment:
    """Same validation as add_range_assignment (subtree membership, exemption,
    same-date conflict) but only constructs the row — does not add/commit/notify.
    Shared by add_range_assignment (single, notifies) and assign_batch (many, one
    commit + one notification pass at the end)."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeValidationError("soldier_not_found")
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    event_node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or event_node is None or event.hierarchy_node_id not in node.path_ids:
        raise RangeValidationError("soldier_outside_event_subunit")
    if is_range_exempt(session, soldier=soldier, event_date=event.date):
        raise RangeValidationError("soldier_range_exempt")
    existing_same_date = session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeEvent.date == event.date,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing_same_date is not None:
        raise RangeValidationError("soldier_already_assigned_on_date")
    return RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_reserve=is_reserve)


def assign_batch(
    session: Session, *, event: RangeEvent,
    primary_soldier_ids: list[uuid.UUID], reserve_soldier_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> list[RangeAssignment]:
    """All-or-nothing: validates every soldier before adding any row, so a single
    invalid soldier in the batch fails the whole call with no partial writes."""
    _acquire_range_assignment_date_lock(session, event_date=event.date)
    session.refresh(event)
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")

    rows = [
        _validate_and_build_assignment(session, event=event, soldier_id=sid, is_reserve=False)
        for sid in primary_soldier_ids
    ] + [
        _validate_and_build_assignment(session, event=event, soldier_id=sid, is_reserve=True)
        for sid in reserve_soldier_ids
    ]
    for row in rows:
        session.add(row)
    session.flush()
    for row in rows:
        create_notification(
            session, soldier_id=row.soldier_id, type=NotificationType.range_assignment_confirmed,
            title="שובצת למטווח", reference_type="range_assignment", reference_id=row.id,
        )
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows
```

Then simplify `add_range_assignment`'s body to call `_validate_and_build_assignment` instead of duplicating the checks inline (keep its existing lock/status/commit/notify wrapper — only the per-soldier validation block moves into the shared helper). Verify the existing `test_ranges_service.py`/`test_range_authorization.py` tests for `add_range_assignment` still pass unchanged after this refactor (their public behavior must not change).

- [ ] **Step 4: Implement — route**

In `backend/app/routes/ranges.py`, add after `add_assignment`:

```python
class BatchAssignBody(BaseModel):
    primaries: list[uuid.UUID] = []
    reserves: list[uuid.UUID] = []


@router.post("/{event_id}/assignments/batch", response_model=list[RangeAssignmentOut])
def batch_assign(
    event_id: uuid.UUID,
    body: BatchAssignBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeAssignmentOut]:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        created = svc.assign_batch(
            session, event=event,
            primary_soldier_ids=body.primaries, reserve_soldier_ids=body.reserves,
            actor_id=user.id,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [_assignment_out(a) for a in created]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_range_batch_assign.py tests/unit/test_ranges_service.py tests/unit/test_range_authorization.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ranges.py backend/app/routes/ranges.py backend/tests/unit/test_range_batch_assign.py
git commit -m "feat: add batch-assign endpoint for range events"
```

### Task B3: Frontend API client — candidates + batch-assign

**Files:**
- Modify: `frontend/src/api/ranges.ts`

**Interfaces:**
- Produces: `interface RangeCandidate {soldier_id: string; full_name: string; personal_number: string; reason_code: string; blocked: boolean; blocked_reason: string | null}`, `getRangeCandidates(eventId: string): Promise<RangeCandidate[]>`, `batchAssignRange(eventId: string, input: {primaries: string[]; reserves: string[]}): Promise<RangeAssignment[]>`.

- [ ] **Step 1: Implement (no test — this is a thin typed wrapper matching the existing untested style of every other function in this file, e.g. `autoAssignRange` at `ranges.ts:20` has no dedicated unit test either; it's covered transitively by the component tests in Task B4/B5)**

In `frontend/src/api/ranges.ts`, add:

```ts
export interface RangeCandidate {
  soldier_id: string;
  full_name: string;
  personal_number: string;
  reason_code: string;
  blocked: boolean;
  blocked_reason: string | null;
}

export function getRangeCandidates(eventId: string): Promise<RangeCandidate[]> {
  return api.get<RangeCandidate[]>(`/ranges/${eventId}/candidates`).then(r => r.data);
}

export function batchAssignRange(eventId: string, input: { primaries: string[]; reserves: string[] }): Promise<RangeAssignment[]> {
  return api.post<RangeAssignment[]>(`/ranges/${eventId}/assignments/batch`, input).then(r => r.data);
}
```

(Match the exact `api.get`/`api.post` call style already used by the neighboring functions in this file — read a few lines above/below the insertion point first and mirror them precisely, since this file mixes `(await api.get(...)).data` and `.then(r => r.data)` styles inconsistently; use whichever the immediately-adjacent function uses.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no consumers yet, so this alone can't fail beyond a syntax error).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/ranges.ts
git commit -m "feat: add candidates/batch-assign API client functions"
```

### Task B4: Frontend — candidate panel replaces auto-assign button, draft/confirm UI removed

Rework `RangeEditAssignmentsModal.tsx`'s primary/reserve "add soldier" flow: replace the free-text search box with a persistent ranked candidate list (fetched via `getRangeCandidates`) with checkboxes per soldier, a "בחר אוטומטית" button per section (primary/reserve) that pre-checks the top-N unblocked candidates (mirroring `autoSelectPrimary`/`autoSelectReserves` at `frontend/src/components/ShiftEditAssignmentsModal.tsx:193-203`), and a single "שמור שיבוצים" button that calls `batchAssignRange` once. Remove the old one-click "שיבוץ אוטומטי" button, the draft badges, and the confirm/confirm-all buttons — nothing produces drafts anymore (Task B2's `assign_batch` always creates `is_draft=False` rows, and `add_range_assignment` already did too), so there is nothing left to confirm.

**Files:**
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx`

**Interfaces:**
- Consumes: `getRangeCandidates`, `batchAssignRange`, `RangeCandidate` (Task B3); existing `RangeAssignment`, `RangeEvent`, `removeRangeAssignment`, `updateRangeAssignmentReason` (unchanged, still used for the existing roster list + reason-edit + remove flows, which this task does not touch).
- Produces: `RangeEditAssignmentsModal`'s public `Props` interface is unchanged (same `open`/`event`/`soldiers`/`canManage`/`onClose`/`onChanged`).

- [ ] **Step 1: Write the failing test**

Replace the following existing tests in `frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx` (their premises — draft badges, one-click auto-assign, confirm/confirm-all, free-text search-then-add — no longer hold):
- `"renders primary and reserve sections and marks existing drafts"` (drop the draft-badge assertion; drafts can no longer exist)
- `"adds a soldier with the reserve toggle and refreshes the event"`
- `"supports auto-assignment and confirming one or all drafts"`
- the `it.each` cases for `"auto"` and `"confirm"` in `"shows a user-facing error when %s fails"`
- `"shows an error when confirming all drafts fails"`
- the `"keeps the roster visible but hides every assignment mutation control from a non-manager"` test's assertions about `range-auto-assign`/`range-confirm-all`/`range-reserve-toggle`/`range-soldier-search`

Replace with:

```tsx
  it("renders the ranked candidate panel with auto-select and lets a manager save a batch", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", blocked: false, blocked_reason: null },
      { soldier_id: "s2", full_name: "דנה", personal_number: "s2", reason_code: "available_and_balanced", blocked: false, blocked_reason: null },
      { soldier_id: "s3", full_name: "רון", personal_number: "s3", reason_code: "available_and_balanced", blocked: true, blocked_reason: "exempt" },
    ]);
    vi.mocked(rangesApi.batchAssignRange).mockResolvedValue([
      { id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null, assignment_reason_code: "qualified", assignment_reason_text: null },
    ]);
    const { props } = renderModal({ event: event([]) });

    await screen.findByText("אורי");
    fireEvent.click(screen.getByTestId("range-auto-select-primary"));
    expect(screen.getByTestId("candidate-checkbox-s1")).toBeChecked();

    fireEvent.click(screen.getByTestId("save-assignments"));
    await waitFor(() => expect(rangesApi.batchAssignRange).toHaveBeenCalledWith("event-1", { primaries: ["s1"], reserves: [] }));
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("shows blocked candidates but keeps their checkbox disabled", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([
      { soldier_id: "s3", full_name: "רון", personal_number: "s3", reason_code: "available_and_balanced", blocked: true, blocked_reason: "exempt" },
    ]);
    renderModal({ event: event([]) });

    const checkbox = await screen.findByTestId("candidate-checkbox-s3");
    expect(checkbox).toBeDisabled();
  });

  it("shows a user-facing error when saving the batch fails", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", blocked: false, blocked_reason: null },
    ]);
    vi.mocked(rangesApi.batchAssignRange).mockRejectedValue(new Error("batch"));
    renderModal({ event: event([]) });

    fireEvent.click(await screen.findByTestId("candidate-checkbox-s1"));
    fireEvent.click(screen.getByTestId("save-assignments"));
    expect(await screen.findByRole("alert")).toHaveTextContent("שמירת השיבוצים נכשלה");
  });
```

And for the non-manager visibility test, replace the removed testids with the new ones:

```tsx
  it("keeps the roster visible but hides every assignment mutation control from a non-manager", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([]);
    renderModal({ canManage: false, event: event([assignment("a1", "s1", false, false)]) });

    expect(screen.getByText("אורי")).toBeInTheDocument();
    expect(screen.queryByTestId("range-auto-select-primary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("save-assignments")).not.toBeInTheDocument();
    expect(screen.queryByTestId("remove-assignment-a1")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ranges/RangeEditAssignmentsModal.test.tsx`
Expected: FAIL — `range-auto-select-primary`/`candidate-checkbox-s1`/`save-assignments` don't exist yet.

- [ ] **Step 3: Implement**

In `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`:
- Import `getRangeCandidates`, `batchAssignRange`, `RangeCandidate` from `../../api/ranges`.
- Remove: `autoAssignRange`, `confirmAllDrafts`, `confirmDraftAssignment` imports (no longer called anywhere in this file); the `query`/`setQuery`/`reserve`/`setReserve` free-text-search state and `candidates`/`add()` derived from `soldiers` prop (the `soldiers: SoldierDTO[]` prop itself stays — Task B5 doesn't remove it, other call sites may still pass it, but it's no longer used for the search box); the `autoAssigning`/`setAutoAssigning`/`shortfall`/`setShortfall`/`confirming`/`setConfirming`/`confirmingAll`/`setConfirmingAll` state; the `autoAssign()`/`confirmDraft()`/`confirmAll()` functions; the draft-badge JSX inside `renderAssignment`; the entire `{editable && <section>...auto-assign/confirm-all/search/candidates list...}` block.
- Add new state: `const [rangeCandidates, setRangeCandidates] = useState<RangeCandidate[]>([]);`, `const [primarySelected, setPrimarySelected] = useState<Set<string>>(new Set());`, `const [reserveSelected, setReserveSelected] = useState<Set<string>>(new Set());`, `const [saving, setSaving] = useState(false);`.
- Fetch candidates on open/event change:

```tsx
  useEffect(() => {
    if (!editable) return;
    getRangeCandidates(event.id).then(setRangeCandidates).catch(() => setRangeCandidates([]));
  }, [event.id, editable]);
```

- Add the auto-select + save logic (mirrors `autoSelectPrimary`/`autoSelectReserves` from `ShiftEditAssignmentsModal.tsx:193-203`, adapted to this file's `primaryFull`/`reserveFull`/`primary.length`/`reserves.length` naming):

```tsx
  const primarySlotsLeft = Math.max(0, event.required_count - primary.length);
  const reserveSlotsLeft = Math.max(0, event.reserve_count - reserves.length);
  const unblockedCandidates = useMemo(() => rangeCandidates.filter(c => !c.blocked), [rangeCandidates]);

  function toggleCandidate(id: string, isReserve: boolean) {
    const setSel = isReserve ? setReserveSelected : setPrimarySelected;
    setSel(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
  }

  function autoSelectPrimary() {
    const top = unblockedCandidates.filter(c => !reserveSelected.has(c.soldier_id)).slice(0, primarySlotsLeft).map(c => c.soldier_id);
    setPrimarySelected(new Set(top));
  }

  function autoSelectReserve() {
    const top = unblockedCandidates.filter(c => !primarySelected.has(c.soldier_id)).slice(0, reserveSlotsLeft).map(c => c.soldier_id);
    setReserveSelected(new Set(top));
  }

  async function saveSelection() {
    if (!editable || saving || (primarySelected.size === 0 && reserveSelected.size === 0)) return;
    setSaving(true);
    setError("");
    try {
      const created = await batchAssignRange(event.id, { primaries: [...primarySelected], reserves: [...reserveSelected] });
      setAssignments(current => [...current, ...created]);
      setPrimarySelected(new Set());
      setReserveSelected(new Set());
      await onChanged();
    } catch {
      setError(text("ranges.errors.save_assignments", "שמירת השיבוצים נכשלה"));
    } finally {
      setSaving(false);
    }
  }
```

- Replace the removed search/auto-assign section with the candidate panel:

```tsx
{editable && <section className="space-y-3 rounded border p-3 dark:border-gray-600">
  <div className="flex items-center justify-between"><h4 className="text-sm font-semibold">{text("ranges.candidates_primary", "מועמדים — ראשי")}</h4><button type="button" data-testid="range-auto-select-primary" disabled={primarySlotsLeft === 0} onClick={autoSelectPrimary} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.auto_select", "בחר אוטומטית")}</button></div>
  <div className="max-h-32 overflow-y-auto">{rangeCandidates.map(c => <label key={`p-${c.soldier_id}`} className="flex items-center gap-2 border-t p-1.5 text-sm dark:border-gray-600"><input type="checkbox" data-testid={`candidate-checkbox-${c.soldier_id}`} disabled={c.blocked || reserveSelected.has(c.soldier_id)} checked={primarySelected.has(c.soldier_id)} onChange={() => toggleCandidate(c.soldier_id, false)} />{c.full_name}{c.blocked && <span className="text-xs text-gray-400">({c.blocked_reason})</span>}</label>)}</div>
  <div className="flex items-center justify-between"><h4 className="text-sm font-semibold">{text("ranges.candidates_reserve", "מועמדים — רזרבה")}</h4><button type="button" data-testid="range-auto-select-reserve" disabled={reserveSlotsLeft === 0} onClick={autoSelectReserve} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.auto_select", "בחר אוטומטית")}</button></div>
  <div className="max-h-32 overflow-y-auto">{rangeCandidates.map(c => <label key={`r-${c.soldier_id}`} className="flex items-center gap-2 border-t p-1.5 text-sm dark:border-gray-600"><input type="checkbox" data-testid={`reserve-candidate-checkbox-${c.soldier_id}`} disabled={c.blocked || primarySelected.has(c.soldier_id)} checked={reserveSelected.has(c.soldier_id)} onChange={() => toggleCandidate(c.soldier_id, true)} />{c.full_name}{c.blocked && <span className="text-xs text-gray-400">({c.blocked_reason})</span>}</label>)}</div>
  <button type="button" data-testid="save-assignments" disabled={saving || (primarySelected.size === 0 && reserveSelected.size === 0)} onClick={() => void saveSelection()} className={`${actionClass} border-green-600 bg-green-600 text-white`}>{saving ? text("ranges.saving", "שומר...") : text("ranges.save_assignments", "שמור שיבוצים")}</button>
</section>}
```

(This deliberately renders two separate candidate lists rather than one shared list with a per-row primary/reserve toggle, to keep the checkbox wiring simple and testable — call out to reviewer as a simplification vs. shifts' single-list-with-two-selection-sets approach, acceptable since ranges' candidate pool is typically much smaller than a shift's.)

- Also remove `draft-badge-*` rendering from `renderAssignment` (the `{a.is_draft && <span data-testid={...}>...}` fragment) and the `{a.is_draft && <button data-testid={\`confirm-draft-${a.id}\`}...}` fragment, since `is_draft` can no longer be `true` on any row this modal creates.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ranges/RangeEditAssignmentsModal.test.tsx`
Expected: PASS.

- [ ] **Step 5: Add the `ranges.errors.save_assignments` fallback consistently**

Check `frontend/src/i18n/he.json`'s `"ranges"` object (around where `"errors"` nested keys for ranges live, e.g. `add_assignment`/`remove_assignment`) and add `"save_assignments": "שמירת השיבוצים נכשלה"` alongside them, matching the existing key style exactly. **Before saving, run `python -c "import json; json.load(open('frontend/src/i18n/he.json', encoding='utf-8'))"` from the repo root and grep for `'^  "errors"'` count in the file to confirm you haven't reintroduced a duplicate top-level `"errors"` key** — a duplicate key bug in this exact file bit an earlier session in this project; the `text()` fallback in the component already covers the UI even if this step is skipped, but do it anyway for consistency with the rest of the file.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ranges/RangeEditAssignmentsModal.tsx frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: replace one-click range auto-assign with a candidate selection panel"
```

### Task B5: Backend — remove the now-dead draft/confirm machinery

Nothing produces `is_draft=True` rows anymore (Task B4 removed the only frontend caller of the old auto-assign endpoint). Remove the dead code rather than leaving it unreachable.

**Files:**
- Modify: `backend/app/routes/ranges.py`
- Modify: `backend/app/services/range_auto_assign.py`
- Modify: `frontend/src/api/ranges.ts`
- Delete: none (keep `backend/tests/unit/test_range_auto_assign.py` but gut it — see Step 1)

**Interfaces:**
- Consumes: none.
- Produces: `propose_range_assignments`, `confirm_draft_assignment`, `confirm_all_drafts`, `_stage_draft_confirmation` are removed from `range_auto_assign.py`; the `/{event_id}/auto-assign`, `/{event_id}/assignments/{assignment_id}/confirm`, `/{event_id}/assignments/confirm-all` routes are removed from `ranges.py`; `autoAssignRange`, `confirmDraftAssignment`, `confirmAllDrafts`, `AutoAssignResult` are removed from `frontend/src/api/ranges.ts`.

- [ ] **Step 1: Update the test that will fail once the code is gone**

`backend/tests/unit/test_range_auto_assign.py` currently tests `propose_range_assignments`/`confirm_draft_assignment`/`confirm_all_drafts` directly. Replace its entire contents with tests for `rank_candidates` (Task B1 already covers most of this in `test_range_candidates.py` — check for overlap; if `test_range_auto_assign.py`'s existing test bodies cover scenarios `test_range_candidates.py` doesn't, port those specific scenarios into `test_range_candidates.py` and delete `test_range_auto_assign.py` entirely rather than leaving a near-empty file). Also check `backend/tests/integration/test_ranges_api.py` and `backend/tests/integration/test_public_settings_ranges.py` (and any other integration test file — grep the whole `backend/tests/` tree for `auto-assign`, `auto_assign_range`, `/confirm`, `confirmDraftAssignment`, `confirmAllDrafts`, `propose_range_assignments`) for any reference to the removed routes/functions and delete those specific test cases (not the whole files, unless a file becomes entirely empty).

- [ ] **Step 2: Run the full backend suite to see current failures from Task B4's frontend-only change (none expected yet — this task hasn't touched backend code)**

Run: `cd backend && pytest -q`
Expected: PASS (Task B4 was frontend-only; backend dead code still compiles and passes, it's just unreachable from the UI now).

- [ ] **Step 3: Remove the dead backend routes**

In `backend/app/routes/ranges.py`, delete the `AutoAssignResponse` class, the `auto_assign` route (`POST /{event_id}/auto-assign`), the `confirm_assignment` route (`POST /{event_id}/assignments/{assignment_id}/confirm`), and the `confirm_all_assignments` route (`POST /{event_id}/assignments/confirm-all`).

- [ ] **Step 4: Remove the dead service functions**

In `backend/app/services/range_auto_assign.py`, delete `propose_range_assignments`, `_stage_draft_confirmation`, `confirm_draft_assignment`, `confirm_all_drafts`. Keep `_candidate_pool`, `_rank_candidate`, `rank_candidates`, and every helper `rank_candidates` depends on (`_qualification_types_at_or_above`, `_best_qualification_valid_until`, `_earliest_future_weapon_duty_start`, `_has_approved_constraint_on_date`, `_has_duty_assignment_on_date`, `_has_range_assignment_on_date`) — note `_candidate_pool` itself is now only used by nothing (it was `propose_range_assignments`'s exclusion-list builder; `rank_candidates` inlines its own soldier-fetch+exclude logic per Task B1's Step 3) — **check whether `_candidate_pool` still has any caller after this deletion; if not, delete it too** rather than leaving an unused function.

- [ ] **Step 5: Remove the dead frontend API client code**

In `frontend/src/api/ranges.ts`, delete `autoAssignRange`, `confirmDraftAssignment`, `confirmAllDrafts`, and the `AutoAssignResult` interface (all now unused after Task B4).

- [ ] **Step 6: Run the full backend and frontend suites**

Run: `cd backend && pytest -q` and `cd frontend && npm test && npm run typecheck && npm run lint`
Expected: PASS on all four.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/ranges.py backend/app/services/range_auto_assign.py backend/tests/unit/test_range_auto_assign.py backend/tests/unit/test_range_candidates.py backend/tests/integration/test_ranges_api.py frontend/src/api/ranges.ts
git commit -m "chore: remove dead range draft/confirm auto-assign code"
```

---

## Part C — Bulk Operations

### Task C1: Row-selection checkboxes on the ranges list

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Produces: `RangesPage`'s local state gains `selectedIds: Set<string>` (mirrors `ShiftsPage.tsx`'s `selectedShiftIds` in spirit, but a `Set` rather than an array — `RangesPage.tsx` already uses `Set` idioms nowhere else, so this is the first; keep it simple, this is a small page). Passed down to `RangePlanningTable` via a new `select`-kind column prepended to the existing column list.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/RangesPage.test.tsx`:

```tsx
  it("selects rows via checkboxes and shows the bulk action bar once at least one is selected", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-2", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");

    expect(screen.queryByTestId("range-bulk-action-bar")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    expect(await screen.findByTestId("range-bulk-action-bar")).toHaveTextContent("1 נבחרו");
    fireEvent.click(screen.getByTestId("select-range-event-2"));
    expect(screen.getByTestId("range-bulk-action-bar")).toHaveTextContent("2 נבחרו");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    expect(screen.getByTestId("range-bulk-action-bar")).toHaveTextContent("1 נבחרו");
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx -t "selects rows via checkboxes"`
Expected: FAIL — `select-range-event-1` not found.

- [ ] **Step 3: Implement**

In `frontend/src/pages/RangesPage.tsx`:
- Add `const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());`.
- Add a toggle helper: `function toggleSelected(id: string) { setSelectedIds(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; }); }`.
- Prepend a selection checkbox to the `rowActions` render (or, better, add it as a genuinely separate leading cell so it doesn't get swallowed by the `flex gap-1 items-center` actions div — check how `RangePlanningTable.tsx` builds its `columns` array and add a new leading `PlanningColumn` entry there instead of stuffing it into `rowActions`):

In `frontend/src/components/ranges/RangePlanningTable.tsx`, add a `selectedIds`/`onToggleSelect` prop and prepend a column:

```tsx
interface Props { rows: RangeEvent[]; onRowClick:(event:RangeEvent)=>void; rowActions:(event:RangeEvent)=>ReactNode; filters?:ReactNode; sort?:ReactNode; loading?: boolean; error?: ReactNode; selectedIds?: Set<string>; onToggleSelect?: (id: string) => void; }
```

and in the `columns` array construction, prepend (only when `onToggleSelect` is provided):

```tsx
const columns: PlanningColumn<RangeEvent>[] = [
  ...(onToggleSelect ? [{ key: "select", label: "", render: (e: RangeEvent) => <input type="checkbox" data-testid={`select-range-${e.id}`} checked={selectedIds?.has(e.id) ?? false} onChange={() => onToggleSelect(e.id)} onClick={(ev: React.MouseEvent) => ev.stopPropagation()} /> } as PlanningColumn<RangeEvent>] : []),
  {key:"date", ...},
  // ...rest of the existing columns unchanged
];
```

(Check `PlanningColumn<T>`'s exact type in `frontend/src/components/planning/PlanningTable.tsx` before writing this — match its `key`/`label`/`render`/`sortValue` field names precisely.)

In `RangesPage.tsx`, pass `selectedIds={selectedIds}` and `onToggleSelect={toggleSelected}` to `<RangePlanningTable>`.

- Render the bulk action bar above the table when `selectedIds.size > 0` (placeholder content for now — Task C2 fills in the real actions):

```tsx
{selectedIds.size > 0 && <div data-testid="range-bulk-action-bar" className="flex items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 dark:border-indigo-800 dark:bg-indigo-950" dir="rtl"><span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{selectedIds.size} נבחרו</span></div>}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx`
Expected: PASS (including all pre-existing tests — the new leading checkbox column must not break any row-click/button-click test; if `onRowClick` fires when clicking the checkbox, add `stopPropagation` as shown above).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/components/ranges/RangePlanningTable.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "feat: add row-selection checkboxes to the ranges list"
```

### Task C2: Bulk action bar — clear assignments, cancel, delete

Mirrors `BulkActionBar`'s `handleClear`/`handleCancel`/`handleDelete` (`frontend/src/pages/ShiftsPage.tsx:265-305`) exactly: client-side `Promise.all`/`Promise.allSettled` loops over the existing single-event endpoints, no new backend code. "Cancel" reuses the existing typed-reason requirement (`RangeCancelDialog`'s pattern) but applies one shared reason to every selected event in the batch, via a small new bulk-cancel dialog (not a reuse of `RangeCancelDialog` itself, since that component is wired to a single `cancelId`, not a list — a new lightweight sibling component is simpler than retrofitting).

**Files:**
- Create: `frontend/src/components/ranges/RangeBulkCancelDialog.tsx`
- Create: `frontend/src/components/ranges/RangeBulkCancelDialog.test.tsx`
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`
- Modify: `frontend/src/api/ranges.ts` (if `removeRangeAssignment` needs looping per-assignment for "clear" — check its existing signature first; it already takes `(eventId, assignmentId)`, no new API function needed)

**Interfaces:**
- Consumes: `cancelRangeEvent(id: string, reason: string): Promise<void>`, `deleteRangeEvent(id: string): Promise<void>`, `removeRangeAssignment(eventId: string, assignmentId: string): Promise<void>` (all already exist in `frontend/src/api/ranges.ts`).
- Produces: `RangeBulkCancelDialog` component with `Props {open: boolean; count: number; onClose: () => void; onConfirm: (reason: string) => Promise<void>}` — same shape as `RangeCancelDialog` plus a `count` prop for the "X events" message.

- [ ] **Step 1: Write the failing test — RangeBulkCancelDialog**

Create `frontend/src/components/ranges/RangeBulkCancelDialog.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RangeBulkCancelDialog from "./RangeBulkCancelDialog";

describe("RangeBulkCancelDialog", () => {
  it("requires a reason and reports the selected count before confirming", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(<RangeBulkCancelDialog open count={3} onClose={vi.fn()} onConfirm={onConfirm} />);

    expect(screen.getByText(/3/)).toBeInTheDocument();
    const confirmButton = screen.getByTestId("confirm-bulk-cancel-button");
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("סיבת הביטול"), { target: { value: "מזג אוויר" } });
    expect(confirmButton).not.toBeDisabled();
    fireEvent.click(confirmButton);
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("מזג אוויר"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ranges/RangeBulkCancelDialog.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement RangeBulkCancelDialog**

Create `frontend/src/components/ranges/RangeBulkCancelDialog.tsx`, mirroring `RangeCancelDialog.tsx`'s structure exactly (same `EventDetailModal` wrapper, same textarea contrast classes fixed in an earlier session — `text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100` — do not reintroduce the unstyled-textarea bug):

```tsx
import { useState } from "react";
import { EventDetailModal } from "../planning";

interface Props { open: boolean; count: number; onClose: () => void; onConfirm: (reason: string) => Promise<void>; }

export default function RangeBulkCancelDialog({ open, count, onClose, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  async function submit() {
    if (!reason.trim() || pending) return;
    setPending(true);
    try { await onConfirm(reason.trim()); setReason(""); onClose(); } finally { setPending(false); }
  }
  return <EventDetailModal open={open} title={`ביטול ${count} מטווחים`} onClose={onClose}>
    <div className="space-y-3">
      <label className="block text-sm">סיבת הביטול<textarea aria-label="סיבת הביטול" value={reason} onChange={e => setReason(e.target.value)} className="mt-1 w-full rounded border p-2 text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100" /></label>
      <button data-testid="confirm-bulk-cancel-button" disabled={!reason.trim() || pending} onClick={submit} className="rounded bg-red-600 px-4 py-2 text-white">אשר ביטול</button>
    </div>
  </EventDetailModal>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ranges/RangeBulkCancelDialog.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit RangeBulkCancelDialog**

```bash
git add frontend/src/components/ranges/RangeBulkCancelDialog.tsx frontend/src/components/ranges/RangeBulkCancelDialog.test.tsx
git commit -m "feat: add bulk range cancellation dialog"
```

- [ ] **Step 6: Write the failing test — bulk actions wired into RangesPage**

Add to `frontend/src/pages/RangesPage.test.tsx`:

```tsx
  it("bulk-deletes only the selected events with no assignments, skipping the rest", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-empty", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח ריק", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-full", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח מלא", required_count: 1, reserve_count: 0, status: "planned",
        assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null }] },
    ]);
    vi.mocked(rangesApi.deleteRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח ריק");
    fireEvent.click(screen.getByTestId("select-range-event-empty"));
    fireEvent.click(screen.getByTestId("select-range-event-full"));
    fireEvent.click(await screen.findByTestId("bulk-delete-button"));

    await waitFor(() => expect(rangesApi.deleteRangeEvent).toHaveBeenCalledWith("event-empty"));
    expect(rangesApi.deleteRangeEvent).not.toHaveBeenCalledWith("event-full");
  });

  it("bulk-cancels selected active events with a shared reason", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "event-2", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-02",
        location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.cancelRangeEvent).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(screen.getByTestId("select-range-event-2"));
    fireEvent.click(await screen.findByTestId("bulk-cancel-button"));
    fireEvent.change(await screen.findByLabelText("סיבת הביטול"), { target: { value: "גשם" } });
    fireEvent.click(screen.getByTestId("confirm-bulk-cancel-button"));

    await waitFor(() => expect(rangesApi.cancelRangeEvent).toHaveBeenCalledWith("event-1", "גשם"));
    expect(rangesApi.cancelRangeEvent).toHaveBeenCalledWith("event-2", "גשם");
  });

  it("bulk-clears all assignments from selected events", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned",
        assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null }] },
    ]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(rangesApi.removeRangeAssignment).mockResolvedValue(undefined);

    renderWithQuery(<RangesPage />);
    await screen.findByText("מטווח א");
    fireEvent.click(screen.getByTestId("select-range-event-1"));
    fireEvent.click(await screen.findByTestId("bulk-clear-button"));

    await waitFor(() => expect(rangesApi.removeRangeAssignment).toHaveBeenCalledWith("event-1", "a1"));
  });
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx -t "bulk-"`
Expected: FAIL — `bulk-delete-button`/`bulk-cancel-button`/`bulk-clear-button` not found.

- [ ] **Step 8: Implement**

In `frontend/src/pages/RangesPage.tsx`:
- Import `RangeBulkCancelDialog` and (if not already imported) `cancelRangeEvent`, `removeRangeAssignment`.
- Add `const [bulkCancelOpen, setBulkCancelOpen] = useState(false);` and `const [bulkBusy, setBulkBusy] = useState(false);`.
- Compute `const selectedEvents = useMemo(() => rows.filter(r => selectedIds.has(r.id)), [rows, selectedIds]);` near the other `useMemo`s.
- Add handlers:

```tsx
  async function bulkDelete() {
    const deletable = selectedEvents.filter(e => count(e, false) === 0 && count(e, true) === 0);
    if (deletable.length === 0) { alert("כל המטווחים הנבחרים מכילים שיבוצים ולא ניתן למחוק אותם."); return; }
    if (!confirm(`למחוק ${deletable.length} מטווחים לצמיתות?`)) return;
    setBulkBusy(true);
    try {
      await Promise.allSettled(deletable.map(e => deleteRangeEvent(e.id)));
      setSelectedIds(new Set());
      await invalidate();
    } finally {
      setBulkBusy(false);
    }
  }

  async function bulkCancel(reason: string) {
    setBulkBusy(true);
    try {
      await Promise.all(selectedEvents.map(e => cancelRangeEvent(e.id, reason)));
      setSelectedIds(new Set());
      await invalidate();
    } finally {
      setBulkBusy(false);
    }
  }

  async function bulkClear() {
    const totalAssignments = selectedEvents.reduce((acc, e) => acc + e.assignments.length, 0);
    if (!confirm(`לנקות שיבוצים מ-${selectedEvents.length} מטווחים (${totalAssignments} שיבוצים)?`)) return;
    setBulkBusy(true);
    try {
      await Promise.all(selectedEvents.flatMap(e => e.assignments.map(a => removeRangeAssignment(e.id, a.id))));
      setSelectedIds(new Set());
      await invalidate();
    } finally {
      setBulkBusy(false);
    }
  }
```

- Replace the placeholder bulk-action-bar `<div>` from Task C1 with the real bar:

```tsx
{selectedIds.size > 0 && <div data-testid="range-bulk-action-bar" className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 dark:border-indigo-800 dark:bg-indigo-950" dir="rtl">
  <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{selectedIds.size} נבחרו</span>
  <button type="button" data-testid="bulk-clear-button" disabled={bulkBusy} onClick={() => void bulkClear()} className="rounded bg-orange-500 px-3 py-1 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-40">נקה שיבוצים</button>
  <button type="button" data-testid="bulk-cancel-button" disabled={bulkBusy} onClick={() => setBulkCancelOpen(true)} className="rounded bg-amber-500 px-3 py-1 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-40">בטל מטווחים</button>
  <button type="button" data-testid="bulk-delete-button" disabled={bulkBusy} onClick={() => void bulkDelete()} className="rounded bg-red-600 px-3 py-1 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40">מחק מטווחים</button>
</div>}
<RangeBulkCancelDialog open={bulkCancelOpen} count={selectedIds.size} onClose={() => setBulkCancelOpen(false)} onConfirm={bulkCancel} />
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/RangesPage.test.tsx`
Expected: PASS (full file — check no earlier test's row-click assertions collide with the new leading checkbox column or the new bar).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "feat: add bulk clear/cancel/delete actions for selected ranges"
```

---

## Part D — Unit Calendar Filter Dropdowns

Separate subsystem from Parts A-C (touches `frontend/src/components/UnitCalendar.tsx`, not the ranges management page). Already implemented and tested; the only remaining step is merging it.

**What changed:** `UnitCalendar.tsx` previously rendered one pill `<button>` per duty type and one per range type (two already-separate filter rows — `dutyTypesInView`/`rangeTypesInView` were never merged into a single row), each toggling a single-selected `string | null` filter. This grows unbounded with the number of duty types and only supported selecting one at a time. Replaced both rows with `CheckboxListDropdown` (`frontend/src/components/CheckboxListDropdown.tsx` — the same component already used by `SwapsPage.tsx` and `ImportSessionReviewPage.tsx`), one dropdown per category, each holding a `string[]` selection (empty = show all, matching the convention `SwapsPage.tsx:539` already uses: `dutyTypeIds: ids.length > 0 ? ids : undefined`). `frontend/src/i18n/he.json`'s `unit_calendar.range_filter_label` was reworded from "סינון מטווחים:" to "מטווחים" (a dropdown trigger label reads better without the colon) and a new `unit_calendar.duty_type_filter_label: "סוגי תורנויות"` key was added for the duty-type dropdown's trigger.

**Verification already done:** `npm run typecheck` clean, `npm run lint` clean (the project's own eslint config doesn't lint `.json` files — a stray direct `eslint src/i18n/he.json` invocation outside the project config flagged unrelated pre-existing duplicate-key warnings in that file; confirmed false-positive/out-of-scope, not caused by this change), full `npm test` 623/623 passing. Live browser verification was attempted but the sandboxed `dev.ps1` stack proved unreliable in that session (served a stale bundle from a leftover process) — a human should do a quick visual check before/after merge.

### Task D1: Merge the calendar filter work into dev

**Files:** none — this is a merge operation, not a code change. If review during the merge step surfaces anything to fix, fix it in the `worktree-calendar-filter-dropdowns` worktree directly and re-verify with `npm test`/`npm run typecheck` before merging.

- [ ] **Step 1: Review the diff**

```bash
cd .claude/worktrees/calendar-filter-dropdowns && git log --oneline dev..HEAD && git diff dev...HEAD -- frontend/src/components/UnitCalendar.tsx frontend/src/i18n/he.json
```

Expected: one commit (`5848cfdc`), a ~29-insertion/48-deletion diff in `UnitCalendar.tsx` plus a 3-line diff in `he.json`.

- [ ] **Step 2: Merge via the project's merge-worktree-to-dev skill**

Follow the project skill `merge-worktree-to-dev` (see `CLAUDE.md` — branch workflow) from the `worktree-calendar-filter-dropdowns` worktree: run the test suite, then merge to `dev` locally, then clean up the worktree per that skill's standard flow. Do not merge directly with a bare `git merge` outside the skill — it also handles the worktree/branch cleanup and the "verify tests on the merged result" step this project requires.

- [ ] **Step 3: Confirm merged `dev` is green**

Run: `cd backend && pytest -q -m duty` and `cd frontend && npm test`
Expected: 100% pass on both, same as pre-merge, confirming no conflict-induced regression (e.g. a duplicate-key or diverged-Alembic-head situation like the ones hit earlier in this project's history — check for those specifically if the merge wasn't a clean fast-forward).

---

## Final Verification

- [ ] **Run the full backend suite**: `cd backend && pytest -q` — expect 100% pass, no new skips beyond the 3 pre-existing solver-flake skips in `test_algorithm_routes.py`.
- [ ] **Run the full frontend suite**: `cd frontend && npm test && npm run typecheck && npm run lint` — expect 100% pass, zero lint warnings.
- [ ] **Grep for now-orphaned references**: `grep -rn "autoAssignRange\|confirmDraftAssignment\|confirmAllDrafts\|propose_range_assignments\|range-soldier-search\|edit-range-assignments" backend/ frontend/src/ --include=*.ts --include=*.tsx --include=*.py` — expect zero matches (all removed in Part B).
- [ ] **Manual smoke check** (if a live preview is available in your environment): open `/ranges`, confirm שיבוצים opens the editor directly, confirm the candidate panel shows ranked/blocked soldiers with a working "בחר אוטומטית", confirm bulk-select shows the action bar and each bulk action works end-to-end against a real backend.
