# Clickable Cumulative Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "ניקוד מצטבר" (cumulative score) number on the transparency page clickable, opening that soldier's duty-history tab pre-filtered to the event types that actually affect score (assignment / cancellation / call_up / dismissal), so the number can be verified against the underlying events.

**Architecture:** `DutyHistoryPanel`'s single-select event-type filter chips become a multiselect `CheckboxListDropdown` (the same reusable component already used by the unit calendar's duty-type filter). `UnifiedSoldierModal` and `SoldierModalContext.openSoldierModal` each grow one new optional parameter to let a caller open the modal on a specific tab with a specific type filter preset. `TransparencyPage`'s cumulative-score cell becomes a button that calls `openSoldierModal` with those two new arguments.

**Tech Stack:** React, TypeScript, Vitest + Testing Library, i18next.

## Global Constraints

- Existing `openSoldierModal(soldierId, onRefresh?)` callers (e.g. `SoldierLink`) must keep working unchanged — new parameters are optional and trailing.
- The status filter row (published/draft/reserve/cancelled) in `DutyHistoryPanel` is untouched.
- Score-affecting event types are exactly `assignment`, `cancellation`, `call_up`, `dismissal` (per `backend/app/services/duty_history.py`, where only these four events carry `score_total` metadata).
- Follow existing patterns: `CheckboxListDropdown` (see `frontend/src/components/UnitCalendar.tsx:229-235`), the `initialEditing` prop pattern on `UnifiedSoldierModal`, and the `effort_score` column's clickable-button styling in `TransparencyPage.tsx:626-636`.

---

### Task 1: Multiselect event-type filter in `DutyHistoryPanel`

**Files:**
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`
- Test: `frontend/src/components/DutyHistoryPanel.test.tsx`

**Interfaces:**
- Consumes: `CheckboxListDropdown` from `./CheckboxListDropdown` (props: `items: {id: string; label: string}[]`, `selected: string[]`, `onChange: (ids: string[]) => void`, `triggerLabel: string`, `panelDir?: "rtl" | "ltr"`).
- Produces: `DutyHistoryPanel` gains a new optional prop `initialTypes?: string[]`. Later tasks (Task 2) rely on this exact prop name and type.

**Current state (for context):** `DutyHistoryPanel.tsx` has a `FilterType` union (`"all" | "assignment" | "algorithm_draft" | "cancellation" | "call_up" | "dismissal" | "exemption" | "exemption_request" | "personal_constraint" | "range"`), a `FILTER_KEYS` array of `{type, i18nKey}` used to render chip buttons (lines ~20-45, ~722-737), a `filter` state (`useState<FilterType>("all")`), and a `matchesFilter` helper + `typeFiltered` computed value (lines ~656-665).

- [ ] **Step 1: Add the new i18n label for the dropdown trigger**

Edit `frontend/src/i18n/he.json`. Find the `"duty_history"` block (starts around line 1106) and add a new key right after `"title"`:

```json
  "duty_history": {
    "title": "היסטוריית תורנויות",
    "filter_types_label": "סוגי אירועים",
    "filter_all": "הכל",
```

- [ ] **Step 2: Write the failing tests for `initialTypes` and the multiselect dropdown**

In `frontend/src/components/DutyHistoryPanel.test.tsx`, replace the existing `describe("DutyHistoryPanel matchesFilter for range events", ...)` block (lines 104-135) with:

```tsx
describe("DutyHistoryPanel event-type filter", () => {
  function threeEvents() {
    return [
      {
        id: "ra1", event_type: "range_assignment", date: "2026-09-01", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון", is_reserve: "false", was_promoted_from_reserve: "false" },
        created_at: "2026-08-01T00:00:00Z",
      },
      {
        id: "rr1", event_type: "range_removed", date: "2026-09-02", end_date: null,
        title: "הוסר ממטווח laser במטווח צפון", description: "חופשה", status: null,
        metadata: { range_type: "laser", location_name: "מטווח צפון", source: "excusal" },
        created_at: "2026-08-01T00:00:00Z",
      },
      {
        id: "a1", event_type: "assignment", date: "2026-09-03", end_date: "2026-09-04",
        title: "שמירה במוצב", description: null, status: "published",
        metadata: {},
        created_at: "2026-08-01T00:00:00Z",
      },
    ];
  }

  it("selecting only the 'range' checkbox shows both range_assignment and range_removed events, and hides assignment", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue(threeEvents());
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    await screen.findByTestId("history-event-range_assignment");

    // Open the dropdown, clear the default "all selected" state, then pick just "range".
    fireEvent.click(screen.getByText("duty_history.filter_types_label"));
    fireEvent.click(screen.getByText("הכל"));
    fireEvent.click(screen.getByText("duty_history.filter_ranges"));

    expect(screen.getByTestId("history-event-range_assignment")).toBeTruthy();
    expect(screen.getByTestId("history-event-range_removed")).toBeTruthy();
    expect(screen.queryByTestId("history-event-assignment")).toBeNull();
  });

  it("initialTypes seeds the filter on mount without needing to open the dropdown", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue(threeEvents());
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} initialTypes={["assignment"]} />);

    await screen.findByTestId("history-event-assignment");
    expect(screen.queryByTestId("history-event-range_assignment")).toBeNull();
    expect(screen.queryByTestId("history-event-range_removed")).toBeNull();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/DutyHistoryPanel.test.tsx`
Expected: FAIL — `getByTestId("history-filter-range")` no longer exists is not the failure (we removed that usage), instead expect failures like "Unable to find an element with the text: duty_history.filter_types_label" (trigger doesn't exist yet) and "initialTypes" prop being unused/ignored (assignment event not isolated, range events still show).

- [ ] **Step 4: Implement the multiselect filter**

In `frontend/src/components/DutyHistoryPanel.tsx`:

Add the import (alongside the other component imports near the top):

```tsx
import CheckboxListDropdown from "./CheckboxListDropdown";
```

Replace the `FilterType` union, `FILTER_KEYS` array (the block currently spanning roughly lines 20-45):

```tsx
type EventTypeFilter =
  | "assignment"
  | "algorithm_draft"
  | "cancellation"
  | "call_up"
  | "dismissal"
  | "exemption"
  | "exemption_request"
  | "personal_constraint"
  | "range";

type StatusFilter = "all" | "published" | "draft" | "reserve" | "cancelled";

const EVENT_TYPE_FILTER_KEYS: { type: EventTypeFilter; i18nKey: string }[] = [
  { type: "assignment", i18nKey: "duty_history.filter_assignments" },
  { type: "algorithm_draft", i18nKey: "duty_history.filter_drafts" },
  { type: "cancellation", i18nKey: "duty_history.filter_cancellations" },
  { type: "call_up", i18nKey: "duty_history.filter_call_ups" },
  { type: "dismissal", i18nKey: "duty_history.filter_dismissals" },
  { type: "exemption", i18nKey: "duty_history.filter_exemptions" },
  { type: "exemption_request", i18nKey: "duty_history.filter_exemption_requests" },
  { type: "personal_constraint", i18nKey: "duty_history.filter_constraints" },
  { type: "range", i18nKey: "duty_history.filter_ranges" },
];

const ALL_EVENT_TYPE_FILTER_IDS = EVENT_TYPE_FILTER_KEYS.map((f) => f.type);

function eventMatchesTypes(e: TimelineEvent, selected: string[]): boolean {
  if (selected.includes("algorithm_draft") && e.status === "algorithm_draft") return true;
  if (selected.includes("range") && (e.event_type === "range_assignment" || e.event_type === "range_removed")) return true;
  return selected.includes(e.event_type);
}
```

(`StatusFilter` is unchanged — kept here verbatim since it sits right next to what's being replaced.)

Update the `Props` interface (currently lines ~108-113) to add `initialTypes`:

```tsx
interface Props {
  soldierId: string;
  soldierName?: string;
  canManage: boolean;
  isActive: boolean;
  initialTypes?: string[];
}
```

Update the component signature and state (currently `export default function DutyHistoryPanel({ soldierId, soldierName, canManage, isActive }: Props) {` at line 471, and `const [filter, setFilter] = useState<FilterType>("all");` at line 477):

```tsx
export default function DutyHistoryPanel({ soldierId, soldierName, canManage, isActive, initialTypes }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [types, setTypes] = useState<string[] | null>(initialTypes ?? null);
```

(Leave every other line of that `useState` block — `statusFilter`, `expanded`, etc. — exactly as they are today.)

Replace the old filtering logic (currently around lines 656-665):

```tsx
const today = new Date().toISOString().slice(0, 10);
const effectiveTypes = types ?? ALL_EVENT_TYPE_FILTER_IDS;
const typeFiltered = events.filter((e) => eventMatchesTypes(e, effectiveTypes));
```

Replace the filter-chip render block (currently the `{/* Filter chips */}` `<div>` around lines 721-737):

```tsx
{/* Event-type filter */}
<div className="flex flex-wrap gap-1 mb-4">
  <CheckboxListDropdown
    items={EVENT_TYPE_FILTER_KEYS.map(({ type, i18nKey }) => ({ id: type, label: t(i18nKey) }))}
    selected={types ?? ALL_EVENT_TYPE_FILTER_IDS}
    onChange={setTypes}
    triggerLabel={t("duty_history.filter_types_label")}
    panelDir="rtl"
  />
</div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/DutyHistoryPanel.test.tsx`
Expected: PASS (all tests in the file, including the two range-event describe blocks already in the file and the new "event-type filter" block).

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DutyHistoryPanel.tsx frontend/src/components/DutyHistoryPanel.test.tsx frontend/src/i18n/he.json
git commit -m "feat: multiselect event-type filter in duty history panel"
```

---

### Task 2: `initialTab` on `UnifiedSoldierModal` and thread `initialHistoryTypes` through

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`
- Test: `frontend/src/components/UnifiedSoldierModal.test.tsx`

**Interfaces:**
- Consumes: `DutyHistoryPanel`'s `initialTypes?: string[]` prop (from Task 1).
- Produces: `UnifiedSoldierModal` gains `initialTab?: TabKey` (exported type) and `initialHistoryTypes?: string[]` optional props. Task 3 relies on both exact names and on `TabKey` being exported from this file.

- [ ] **Step 1: Write the failing test**

In `frontend/src/components/UnifiedSoldierModal.test.tsx`, add a new `describe` block after the existing `renderModal` helper's first usage (anywhere at the top level of the file works; add it at the end of the file):

```tsx
describe("UnifiedSoldierModal initialTab", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
  });

  test("opens directly on the duty_history tab when initialTab is set", async () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <UnifiedSoldierModal
          soldier={soldier}
          score={null}
          nodes={[]}
          onClose={vi.fn()}
          onRefresh={vi.fn()}
          initialTab="duty_history"
        />
      </QueryClientProvider>,
    );

    const historyTabButton = screen.getByTestId("modal-tab-duty_history");
    expect(historyTabButton.className).toContain("border-indigo-600");
    // DutyHistoryPanel mounts and immediately shows its loading state.
    expect(await screen.findByText("app.loading")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/UnifiedSoldierModal.test.tsx -t "opens directly on the duty_history tab"`
Expected: FAIL with a TypeScript error (no `initialTab` prop) or, if TS is not enforced at test-run time, a runtime assertion failure because the `details` tab is active instead.

- [ ] **Step 3: Implement `initialTab`**

In `frontend/src/components/UnifiedSoldierModal.tsx`:

Export `TabKey` (currently line 52, `type TabKey = (typeof ALL_TABS)[number];`, not exported):

```tsx
export type TabKey = (typeof ALL_TABS)[number];
```

Update `Props` (currently lines 42-49):

```tsx
interface Props {
  soldier: SoldierDTO;
  score: SoldierScoreDTO | null;
  nodes: NodeDTO[];
  onClose: () => void;
  onRefresh: () => void;
  initialEditing?: boolean;
  initialTab?: TabKey;
  initialHistoryTypes?: string[];
}
```

Update the component signature (currently line 54):

```tsx
export default function UnifiedSoldierModal({ soldier, score, nodes, onClose, onRefresh, initialEditing = false, initialTab, initialHistoryTypes }: Props) {
```

Update the `tab` state initializer (currently line 78, `const [tab, setTab] = useState<TabKey>("details");`):

```tsx
const [tab, setTab] = useState<TabKey>(initialTab ?? "details");
```

Update the `DutyHistoryPanel` usage (currently lines 723-730) to pass the new prop through:

```tsx
{tab === "duty_history" && (
  <DutyHistoryPanel
    soldierId={soldier.id}
    soldierName={soldier.full_name}
    canManage={canManage}
    isActive={tab === "duty_history"}
    initialTypes={initialHistoryTypes}
  />
)}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/UnifiedSoldierModal.test.tsx`
Expected: PASS (the whole file, including pre-existing tests).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx frontend/src/components/UnifiedSoldierModal.test.tsx
git commit -m "feat: support opening UnifiedSoldierModal on a specific tab with a preset history filter"
```

---

### Task 3: Extend `openSoldierModal` and wire up the cumulative-score button

**Files:**
- Modify: `frontend/src/contexts/SoldierModalContext.tsx`
- Modify: `frontend/src/pages/TransparencyPage.tsx`
- Test: `frontend/src/pages/TransparencyPage.cumulativeScore.test.tsx` (new file)

**Interfaces:**
- Consumes: `UnifiedSoldierModal`'s `initialTab?: TabKey` and `initialHistoryTypes?: string[]` props, and the exported `TabKey` type (from Task 2).
- Produces: `openSoldierModal(soldierId: string, onRefresh?: () => void, initialTab?: TabKey, initialHistoryTypes?: string[])`. No other file consumes this beyond `TransparencyPage.tsx` in this plan.

- [ ] **Step 1: Update `SoldierModalContext`**

In `frontend/src/contexts/SoldierModalContext.tsx`:

Update the import (currently line 11):

```tsx
import UnifiedSoldierModal, { type TabKey } from "../components/UnifiedSoldierModal";
```

Update `SoldierModalContextValue` (currently lines 13-15):

```tsx
interface SoldierModalContextValue {
  openSoldierModal: (soldierId: string, onRefresh?: () => void, initialTab?: TabKey, initialHistoryTypes?: string[]) => void;
}
```

Update `ModalState` (currently lines 25-30):

```tsx
interface ModalState {
  soldier: SoldierDTO;
  score: SoldierScoreDTO | null;
  nodes: NodeDTO[];
  onRefresh?: () => void;
  initialTab?: TabKey;
  initialHistoryTypes?: string[];
}
```

Update `openSoldierModal` (currently lines 36-68):

```tsx
const openSoldierModal = useCallback(
  async (soldierId: string, onRefresh?: () => void, initialTab?: TabKey, initialHistoryTypes?: string[]) => {
    setOpening(true);
    try {
      const [soldier, score, nodes] = await Promise.allSettled([
        getSoldier(soldierId),
        getSoldierScore(soldierId),
        fetchTree(),
      ]);

      if (soldier.status === "rejected") {
        alert("לא ניתן לטעון את פרטי החייל");
        return;
      }

      setModal({
        soldier: (soldier as PromiseFulfilledResult<SoldierDTO>).value,
        score:
          score.status === "fulfilled"
            ? (score as PromiseFulfilledResult<SoldierScoreDTO>).value
            : null,
        nodes:
          nodes.status === "fulfilled"
            ? (nodes as PromiseFulfilledResult<NodeDTO[]>).value
            : [],
        onRefresh,
        initialTab,
        initialHistoryTypes,
      });
    } finally {
      setOpening(false);
    }
  },
  []
);
```

Update the `UnifiedSoldierModal` render (currently lines 90-98):

```tsx
{modal && (
  <UnifiedSoldierModal
    key={modal.soldier.id}
    soldier={modal.soldier}
    score={modal.score}
    nodes={modal.nodes}
    onClose={handleClose}
    onRefresh={handleRefresh}
    initialTab={modal.initialTab}
    initialHistoryTypes={modal.initialHistoryTypes}
  />
)}
```

- [ ] **Step 2: Write the failing test for the cumulative-score button**

Create `frontend/src/pages/TransparencyPage.cumulativeScore.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import "../i18n";
import TransparencyPage from "./TransparencyPage";
import * as scoringApi from "../api/scoring";
import * as hierarchyApi from "../api/hierarchy";
import * as potentialApi from "../api/potential";
import type { TransparencyOut, TransparencyRow } from "../api/scoring";

vi.mock("../api/scoring");
vi.mock("../api/hierarchy");
vi.mock("../api/potential");

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "viewer-1", role: "admin" } }),
}));

const mockOpenSoldierModal = vi.fn();
vi.mock("../contexts/SoldierModalContext", () => ({
  useSoldierModal: () => ({ openSoldierModal: mockOpenSoldierModal }),
}));

function makeRow(overrides: Partial<TransparencyRow> = {}): TransparencyRow {
  return {
    soldier_id: "s1",
    full_name: "חייל בדיקה",
    node_id: "node-1",
    node_name: "יחידה 1",
    enrolled_at: "2026-01-01",
    active_days: 10,
    shift_count: 2,
    rank: null,
    is_officer: false,
    service_type: "חובה",
    cumulative_score: "1.00",
    score_per_day: "0.10",
    normalised_score: "1.00",
    is_globally_exempted: false,
    effort_score: 0.1,
    c_over_d: 0,
    effort_offset_raw: 0,
    exemptions_display: "",
    exemptions_visible: true,
    exemptions: [],
    has_global_exemption: false,
    has_partial_exemption: false,
    has_temporary_exemption: false,
    ...overrides,
  };
}

beforeEach(() => {
  mockOpenSoldierModal.mockReset();
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(scoringApi.getFairnessComponents).mockRejectedValue(new Error("not needed"));
  vi.mocked(potentialApi.getEffortGap).mockResolvedValue([]);
});

describe("TransparencyPage cumulative score button", () => {
  it("opens the soldier modal on the duty_history tab, filtered to score-affecting event types", async () => {
    const out: TransparencyOut = {
      rows: [makeRow()],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><TransparencyPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    const scoreButton = await screen.findByRole("button", { name: "1.000" });
    fireEvent.click(scoreButton);

    await waitFor(() => {
      expect(mockOpenSoldierModal).toHaveBeenCalledWith(
        "s1",
        undefined,
        "duty_history",
        ["assignment", "cancellation", "call_up", "dismissal"],
      );
    });
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/TransparencyPage.cumulativeScore.test.tsx`
Expected: FAIL — no button with accessible name "1.000" exists yet (the cell is plain text), so `findByRole` times out.

- [ ] **Step 4: Wire up the button in `TransparencyPage.tsx`**

Add the import (alongside the other imports near the top, e.g. right after the `SoldierLink` import at line 14):

```tsx
import { useSoldierModal } from "../contexts/SoldierModalContext";
```

Add a module-level constant near the top of the file (e.g. right after the `flattenTree`/`gapColor` helper functions, before `export default function TransparencyPage()`):

```tsx
const SCORE_AFFECTING_TYPES = ["assignment", "cancellation", "call_up", "dismissal"];
```

Inside `export default function TransparencyPage() {`, add the hook call near the other hooks at the top (e.g. right after `const { user } = useAuth();` at line 273):

```tsx
const { openSoldierModal } = useSoldierModal();
```

Replace the `cumulative` column definition (currently lines 590-594):

```tsx
{
  id: "cumulative", header: t("transparency.cumulative"),
  headerTooltip: "לחץ על הערך לצפייה באירועים שמשפיעים על הניקוד (תורנויות, ביטולים, הקפצות, שחרורים).",
  cell: (r) => {
    const n = Number(r.cumulative_score);
    const label = isNaN(n) ? r.cumulative_score : n.toFixed(3);
    return (
      <button
        className="text-indigo-600 dark:text-indigo-300 hover:underline font-medium"
        onClick={() => openSoldierModal(r.soldier_id, undefined, "duty_history", SCORE_AFFECTING_TYPES)}
        title="לחץ לצפייה באירועים שמשפיעים על הניקוד"
      >
        {label}
      </button>
    );
  },
  sortValue: (r) => Number(r.cumulative_score),
},
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/TransparencyPage.cumulativeScore.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full existing `TransparencyPage.test.tsx` suite to confirm no regression**

Run: `cd frontend && npx vitest run src/pages/TransparencyPage.test.tsx`
Expected: PASS — in particular the "rounds the cumulative score to 3 decimal places" test (line 278 area), which uses `getByText("9.030")`; this still matches since the text is now inside a `<button>` rather than a bare text node, and Testing Library's `getByText` matches by element text content regardless of the wrapping tag.

- [ ] **Step 7: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors, zero warnings.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/contexts/SoldierModalContext.tsx frontend/src/pages/TransparencyPage.tsx frontend/src/pages/TransparencyPage.cumulativeScore.test.tsx
git commit -m "feat: make transparency page cumulative score clickable to show score-affecting duty history"
```

---

### Task 4: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests pass, no regressions outside the files touched above.

- [ ] **Step 2: Run typecheck and lint one more time on the whole project**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors, zero warnings.

- [ ] **Step 3: Manual smoke test in the browser**

Start the dev stack (`.\dev.ps1` from the repo root), log in as an admin, go to the transparency page, and:
1. Confirm the cumulative-score column values are now indigo, underlined buttons.
2. Click one. Confirm the soldier modal opens directly on the "היסטוריית תורנויות" tab.
3. Confirm the event-type dropdown shows a badge count of 4 and that only assignment/cancellation/call_up/dismissal events are visible.
4. Open the dropdown and confirm all 9 event-type checkboxes are listed with correct Hebrew labels, and toggling them shows/hides events as expected.
5. Confirm clicking a soldier's name (`SoldierLink`) elsewhere still opens the modal on the "פרטים" (details) tab as before — no regression to the default flow.
