# Upcoming-duties soldier modal: close-X + שחרור פיקודי shortcut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bottom `ביטול` button in the commander dashboard's upcoming-duty soldier modal with a header `✕` close button, and add a `שחרור פיקודי` action that confirms with the user, then deep-links into the existing הקפצה פיקודית (`HakpazaPage`) flow pre-filled with that soldier and assignment.

**Architecture:** Two independent, sequential frontend-only changes. Task 1 touches only `UpcomingSnapshot.tsx` (modal UI + navigation). Task 2 touches only `HakpazaPage.tsx` (reads query params on mount to pre-populate step 1/2 of the existing wizard). No backend or API changes — `getSoldier` and `listAssignments` already exist and cover everything needed.

**Tech Stack:** React + TypeScript, react-router-dom, vitest + @testing-library/react.

## Global Constraints

- Hebrew UI strings, English code/identifiers (per project convention).
- Confirmation must use `window.confirm` — this codebase has no shared `ConfirmDialog` component; `window.confirm` is the established pattern (see `ShiftsPage.tsx`).
- Close button must match the existing modal convention: `aria-label="סגור"`, `className="text-gray-400 hover:text-gray-600 text-xl leading-none"`, rendered as `✕`.
- No new backend endpoints or API client functions — only `getSoldier(id)` (`frontend/src/api/soldiers.ts:141`) and `listAssignments(soldierId, params)` (`frontend/src/api/assignments.ts:29`), both of which already exist.
- Run `npm run typecheck` and `npm run lint` (from `frontend/`) after both tasks, plus targeted `npm test` for the two new/changed test files — do not run the full suite mid-task.

---

### Task 1: Modal close-X + שחרור פיקודי button (`UpcomingSnapshot.tsx`)

**Files:**
- Modify: `frontend/src/components/UpcomingSnapshot.tsx`
- Test: `frontend/src/components/UpcomingSnapshot.test.tsx` (new)

**Interfaces:**
- Consumes: `UpcomingAssignment` type from `frontend/src/api/commanderDashboard.ts:44` (`assignment_id`, `soldier_id`, `soldier_name`, `duty_type_id`, `duty_type_name`, `node_name`, `is_reserve` — all already present, no changes needed).
- Produces: no new exports; this is a leaf UI component. Later Task 2 relies on the query-string shape this task produces: `/commander/hakpaza?soldierId={soldier_id}&assignmentId={assignment_id}`.

Current modal markup (for reference, `frontend/src/components/UpcomingSnapshot.tsx:56-74`):

```tsx
{selected && (
  <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 w-72" onClick={(e) => e.stopPropagation()}>
      <div className="font-bold text-lg mb-3">
        {selected.soldier_id ? (
          <SoldierLink id={selected.soldier_id} name={selected.soldier_name || "?"} />
        ) : (
          selected.soldier_name || "?"
        )}
      </div>
      <div className="space-y-1 text-sm">
        <div><span className="text-gray-500 dark:text-gray-400">תורנות:</span> {selected.duty_type_name || selected.duty_type_id?.slice(0, 6) || "?"}</div>
        <div><span className="text-gray-500 dark:text-gray-400">יחידה:</span> {selected.node_name || "?"}</div>
        {selected.is_reserve && <div className="text-amber-700 dark:text-amber-400 font-medium">רזרבה</div>}
      </div>
      <button onClick={() => setSelected(null)} className="mt-4 px-3 py-1 border dark:border-gray-600 dark:text-gray-300 rounded text-sm">{t("command_dashboard.cancel")}</button>
    </div>
  </div>
)}
```

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/UpcomingSnapshot.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import UpcomingSnapshot from "./UpcomingSnapshot";
import type { UpcomingDay } from "../api/commanderDashboard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("./SoldierLink", () => ({
  default: ({ name }: { name: string }) => <span>{name}</span>,
}));

const data: UpcomingDay[] = [
  {
    date: "2026-07-06",
    assignments: [
      {
        assignment_id: "asg-1",
        soldier_id: "sol-1",
        soldier_name: "דני כהן",
        duty_type_id: "dt-1",
        duty_type_name: "שמירות",
        node_name: "ספקטרה",
        is_reserve: false,
      },
    ],
  },
];

beforeEach(() => {
  mockNavigate.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <UpcomingSnapshot data={data} />
    </MemoryRouter>
  );
}

describe("UpcomingSnapshot soldier modal", () => {
  it("opens the modal on badge click and closes it via the ✕ button (no bottom ביטול button)", () => {
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    expect(screen.getByText("שמירות")).toBeInTheDocument();
    expect(screen.queryByText("command_dashboard.cancel")).not.toBeInTheDocument();
    const closeBtn = screen.getByLabelText("סגור");
    fireEvent.click(closeBtn);
    expect(screen.queryByText("שמירות")).not.toBeInTheDocument();
  });

  it("shows a confirm dialog naming the soldier and mentioning קיצוניים, then navigates to the pre-filled hakpaza URL", () => {
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    fireEvent.click(screen.getByText("שחרור פיקודי"));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("דני כהן"));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("קיצוניים"));
    expect(mockNavigate).toHaveBeenCalledWith("/commander/hakpaza?soldierId=sol-1&assignmentId=asg-1");
  });

  it("does not navigate when the confirm dialog is dismissed", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    fireEvent.click(screen.getByText("שחרור פיקודי"));
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/UpcomingSnapshot.test.tsx`
Expected: FAIL — `שחרור פיקודי` text and `סגור` label don't exist yet; `useNavigate` isn't imported/called yet.

- [ ] **Step 3: Implement the modal changes**

Replace the modal block in `frontend/src/components/UpcomingSnapshot.tsx`. First, add the import and hook:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { UpcomingDay, UpcomingAssignment } from "../api/commanderDashboard";
import SoldierLink from "./SoldierLink";
```

Inside the component, add `const navigate = useNavigate();` alongside the existing `useState` calls, and a handler:

```tsx
function handleForcedRelease(a: UpcomingAssignment) {
  const confirmed = window.confirm(
    `פעולה זו תפעיל מנגנון הקפצה פיקודית עבור ${a.soldier_name || "החייל"} — מיועד למקרים קיצוניים בלבד (מחלה, צורך מבצעי דחוף). להמשיך?`
  );
  if (!confirmed) return;
  navigate(`/commander/hakpaza?soldierId=${a.soldier_id}&assignmentId=${a.assignment_id}`);
}
```

Then replace the modal markup:

```tsx
{selected && (
  <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 w-72" onClick={(e) => e.stopPropagation()}>
      <div className="flex justify-between items-start mb-3">
        <div className="font-bold text-lg">
          {selected.soldier_id ? (
            <SoldierLink id={selected.soldier_id} name={selected.soldier_name || "?"} />
          ) : (
            selected.soldier_name || "?"
          )}
        </div>
        <button onClick={() => setSelected(null)} aria-label="סגור" className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
      </div>
      <div className="space-y-1 text-sm">
        <div><span className="text-gray-500 dark:text-gray-400">תורנות:</span> {selected.duty_type_name || selected.duty_type_id?.slice(0, 6) || "?"}</div>
        <div><span className="text-gray-500 dark:text-gray-400">יחידה:</span> {selected.node_name || "?"}</div>
        {selected.is_reserve && <div className="text-amber-700 dark:text-amber-400 font-medium">רזרבה</div>}
      </div>
      {selected.soldier_id && (
        <button
          onClick={() => handleForcedRelease(selected)}
          className="mt-4 w-full px-3 py-1.5 rounded text-sm font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800"
        >
          שחרור פיקודי
        </button>
      )}
    </div>
  </div>
)}
```

Note the bottom `ביטול` button (`t("command_dashboard.cancel")`) is removed entirely — closing is now only via the `✕`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/components/UpcomingSnapshot.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Typecheck and lint**

Run (from `frontend/`): `npm run typecheck` then `npm run lint`
Expected: both clean (no new errors/warnings)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UpcomingSnapshot.tsx frontend/src/components/UpcomingSnapshot.test.tsx
git commit -m "feat: replace modal cancel button with close-X and add שחרור פיקודי shortcut"
```

---

### Task 2: HakpazaPage pre-fill from query params (`HakpazaPage.tsx`)

**Files:**
- Modify: `frontend/src/pages/HakpazaPage.tsx`
- Test: `frontend/src/pages/HakpazaPage.test.tsx` (new)

**Interfaces:**
- Consumes: query params `soldierId` / `assignmentId` produced by Task 1's navigation (`/commander/hakpaza?soldierId=...&assignmentId=...`); `getSoldier(id): Promise<SoldierDTO>` (`frontend/src/api/soldiers.ts:141`); `listAssignments(soldierId, { date_from }): Promise<Assignment[]>` (`frontend/src/api/assignments.ts:29`); existing component state setters `setPulledSoldier`, `setAssignments`, `setSelectedAssignment`, `setPullDate`, `setStep`, `setError`.
- Produces: no new exports — this is a page component. Behavior change only: when both query params are present and valid, the wizard opens on step 2 with the soldier/assignment already selected.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/HakpazaPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import HakpazaPage from "./HakpazaPage";
import * as soldiersApi from "../api/soldiers";
import * as assignmentsApi from "../api/assignments";
import * as dutyConfigApi from "../api/dutyConfig";

vi.mock("../api/soldiers");
vi.mock("../api/assignments");
vi.mock("../api/dutyConfig");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const soldier = { id: "sol-1", full_name: "דני כהן", rank: null } as soldiersApi.SoldierDTO;
const publishedAssignment = {
  id: "asg-1",
  soldier_id: "sol-1",
  duty_type_id: "dt-1",
  duty_location_id: "loc-1",
  start_date: "2099-01-10",
  end_date: "2099-01-15",
  status: "published",
  notes: null,
};

beforeEach(() => {
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([soldier]);
  vi.mocked(soldiersApi.getSoldier).mockResolvedValue(soldier);
  vi.mocked(assignmentsApi.listAssignments).mockResolvedValue([publishedAssignment]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HakpazaPage />
    </MemoryRouter>
  );
}

describe("HakpazaPage query-param pre-fill", () => {
  it("skips to step 2 with the soldier and assignment pre-selected when valid query params are present", async () => {
    renderAt("/commander/hakpaza?soldierId=sol-1&assignmentId=asg-1");
    await waitFor(() => expect(soldiersApi.getSoldier).toHaveBeenCalledWith("sol-1"));
    await waitFor(() => expect(screen.getByText("שלב 2 — בחר תורנות ותאריך הקפצה")).toBeInTheDocument());
    expect(screen.getByText("דני כהן")).toBeInTheDocument();
  });

  it("falls back to step 1 with an error when assignmentId does not match any published assignment", async () => {
    renderAt("/commander/hakpaza?soldierId=sol-1&assignmentId=does-not-exist");
    await waitFor(() => expect(soldiersApi.getSoldier).toHaveBeenCalledWith("sol-1"));
    await waitFor(() => expect(screen.getByText("לא נמצאה התורנות המבוקשת — בחר חייל ידנית")).toBeInTheDocument());
    expect(screen.getByText("שלב 1 — בחר חייל להקפיץ")).toBeInTheDocument();
  });

  it("behaves as before (step 1, no pre-fill) when no query params are present", async () => {
    renderAt("/commander/hakpaza");
    await waitFor(() => expect(soldiersApi.listSoldiers).toHaveBeenCalled());
    expect(soldiersApi.getSoldier).not.toHaveBeenCalled();
    expect(screen.getByText("שלב 1 — בחר חייל להקפיץ")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/pages/HakpazaPage.test.tsx`
Expected: FAIL — no pre-fill effect exists yet, `getSoldier` is never called, no "לא נמצאה התורנות המבוקשת" error text exists.

- [ ] **Step 3: Implement the pre-fill effect**

In `frontend/src/pages/HakpazaPage.tsx`, update imports:

```tsx
import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import Layout from "../components/Layout";
import { SoldierDTO, listSoldiers, getSoldier } from "../api/soldiers";
import { Assignment, listAssignments } from "../api/assignments";
import { Candidate, createHakpaza, findCandidates } from "../api/hakpaza";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { formatDate, formatDutyRange, lastDutyDay } from "../utils/formatDate";
```

Add `const [searchParams] = useSearchParams();` near the other `useState` declarations, then add a new effect after the existing two `useEffect` blocks (i.e. after the `scopedSoldiers`-driven `nextShiftBySoldier` effect):

```tsx
useEffect(() => {
  const soldierId = searchParams.get("soldierId");
  const assignmentId = searchParams.get("assignmentId");
  if (!soldierId || !assignmentId) return;
  let cancelled = false;
  const todayStr = new Date().toISOString().split("T")[0];

  (async () => {
    try {
      const [soldier, asgns] = await Promise.all([
        getSoldier(soldierId),
        listAssignments(soldierId, { date_from: todayStr }),
      ]);
      if (cancelled) return;
      const published = asgns.filter((a) => a.status === "published");
      const match = published.find((a) => a.id === assignmentId);
      setPulledSoldier(soldier);
      setAssignments(published);
      if (match) {
        setSelectedAssignment(match);
        setPullDate(match.start_date >= todayStr ? match.start_date : todayStr);
        setStep(2);
      } else {
        setError("לא נמצאה התורנות המבוקשת — בחר חייל ידנית");
      }
    } catch {
      if (!cancelled) setError("לא נמצאה התורנות המבוקשת — בחר חייל ידנית");
    }
  })();

  return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []);
```

The `eslint-disable` is needed because this effect must run exactly once on mount regardless of `searchParams` identity changes (matches the existing codebase's pattern of intentionally-empty dependency arrays for one-time mount effects — see the `listSoldiers` effect earlier in this same file).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/pages/HakpazaPage.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Typecheck and lint**

Run (from `frontend/`): `npm run typecheck` then `npm run lint`
Expected: both clean (no new errors/warnings)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/HakpazaPage.tsx frontend/src/pages/HakpazaPage.test.tsx
git commit -m "feat: pre-fill hakpaza wizard from soldierId/assignmentId query params"
```

---

## Final check

- [ ] **Step 1: Run both new test files together**

Run (from `frontend/`): `npx vitest run src/components/UpcomingSnapshot.test.tsx src/pages/HakpazaPage.test.tsx`
Expected: PASS (6 tests total)

- [ ] **Step 2: Manual verification in the browser**

Start the dev stack (`.\dev.ps1` from repo root), open the commander dashboard, click a soldier badge in the upcoming-duties widget, confirm the modal shows a `✕` (no bottom `ביטול` button), click `שחרור פיקודי`, confirm the dialog text, confirm it navigates to `/commander/hakpaza` with the wizard already on step 2 for that soldier/assignment.
