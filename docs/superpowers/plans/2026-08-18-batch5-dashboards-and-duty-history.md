# Batch 5 — Dashboards & Duty History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three user-reported issues from the triage spec (`docs/superpowers/specs/2026-08-18-user-reported-issues-triage-design.md`,
Batch 5 / items 6, 14, 16): the commander dashboard duplicates the full
interactive hierarchy tree instead of a summary, upcoming-duty widgets hide
`algorithm_draft` assignments behind a published-only filter, and duty-history
visibility for commanders needed verification against the current
`can_view_soldier_scope` gate.

**Architecture:** Each of the three items is a self-contained frontend/backend
change verified by new tests.

- **B5.1** removes dead state (`_activePanel`/`handleCardClick`) and swaps the
  dashboard's "soldiers" panel from the fully-interactive `HierarchyTree` (add/
  remove/edit soldiers, rename nodes, assign commanders) to a read-only count
  summary + a link to `/team`, which already hosts the same `HierarchyTree` with
  full management capabilities. No backend changes.
- **B5.2** is a display-only widening of "upcoming duties" to include
  `algorithm_draft` assignments across two independent surfaces: the commander
  dashboard's `upcoming_duties`/`summary_cards` (raw `DutyAssignment` queries in
  `backend/app/services/commander_dashboard.py`, no relation to scoring) and the
  soldier's own `UpcomingDutiesWidget` on `HomePage.tsx` (fed by
  `GET /assignments/effective`, which is a thin wrapper over
  `scoring.effective_duty_spans` — the function scoring/effort/fairness read
  from). Because that function must never see drafts, its body is extracted
  into a private `_effective_duty_spans_impl(session, *, statuses, ...)` helper
  parameterized by assignment status; `effective_duty_spans` becomes a
  one-line wrapper that still hardcodes `statuses=["published"]` (identical
  behavior, verified by a new regression test), and a new
  `effective_duty_spans_with_drafts` wrapper (statuses=`["published",
  "algorithm_draft"]`) is added for display use only. The `/assignments/effective`
  route gains an opt-in `include_drafts` query flag (default `False`, matching
  the existing `include_drafts` convention already used by
  `GET /soldiers/{id}/duty-history`); only the `HomePage.tsx` upcoming-duties
  call site passes `include_drafts=true`, so every other consumer of that route
  (`DutyHistoryPanel`, `OfferSwapModal`, `ShiftDetailPanel`, `MyDutiesPage`,
  `SwapsPage`) is unaffected — those surfaces are Batch 4's concern per the
  spec's DC4, not this batch's.
- **B5.3** is a verification-only item: reading `backend/app/services/authority.py`
  (`can_view_soldier_scope`) and its existing test coverage
  (`backend/app/services/tests/test_authority.py`,
  `backend/tests/integration/test_soldiers_api.py`) shows the commander-in-scope
  override for duty-history already exists and is already covered end-to-end —
  see "Investigation finding" below. This batch adds one targeted frontend
  regression test locking the remaining unverified layer (the modal tab) and,
  per the plan's self-review, does not touch backend code for this item.

**Investigation finding (documented per the task brief's requirement to state
this explicitly):** `backend/app/services/authority.py::can_view_soldier_scope`
(consumed directly by `GET /soldiers/{soldier_id}/duty-history` in
`backend/app/routes/soldiers.py:583`) already grants access to any commander
whose commanded node is an ancestor-or-self of the target soldier's node,
*before* falling through to the global `transparency.min_visible_level`
threshold check — i.e. a commander in scope already bypasses the restrictive
transparency default. This is exercised today by
`test_commander_sees_own_subtree_always`
(`backend/app/services/tests/test_authority.py:288`) at the unit level and by
`test_duty_history_200_for_plain_soldier_commanding_target_node`
(`backend/tests/integration/test_soldiers_api.py:272`) at the HTTP level — the
latter uses the *default* (restrictive) `transparency.min_visible_level` and
still asserts `200`, which is precisely the "commander in scope, restrictive
transparency" scenario item 16 describes. On the frontend,
`frontend/src/components/UnifiedSoldierModal.tsx`'s `TABS` array (line 66-70)
already includes `"duty_history"` in **all three** branches (`canViewAll`,
`isSelf`, and the fallback) — the tab is never conditionally hidden. No
production code in either layer needs to change for item 16; Task 8 below adds
the one piece of coverage that was missing (a component-level regression test)
to lock this in and catch future regressions.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Vitest +
`@tanstack/react-query` + `react-router-dom` (frontend), pytest (backend
tests, markers: `soldiers`, `scoring`, `duty`, `misc`).

## Global Constraints

- Scoring/effort isolation: `algorithm_draft` status must never enter scoring,
  effort, or fairness inputs. `backend/app/services/scoring.py::effective_duty_spans`
  keeps its exact existing signature and behavior (published-only) — B5.2 adds
  a new, separate function for display use, it does not widen the existing
  one's filter.
- Date-range convention: `end_date` is exclusive only for assignments and
  cancellations; everything else (constraints, exemptions, dismissals,
  call-ups) is inclusive. No date-range display logic is touched in this batch.
- RBAC: all permission/visibility changes must go through the existing authz
  pattern (`app.auth.authz` / `authorize()`/`can()`, or the
  `app.services.authority` level-check helper family). UI gating must mirror
  backend capability exactly — this batch adds no new gates (B5.1 is UI-only
  simplification with no new permission surface, B5.2's `include_drafts` flag
  requires no additional authorization beyond the existing `SOLDIER_READ`
  check already on the route, and B5.3 makes no permission changes at all).
- Tests: backend (`pytest -q` fast suite, plus `pytest -m "duty or scoring"
  -q`) and frontend (`npm test`, `npm run lint` zero-warnings, `npm run
  typecheck`) must stay green throughout.

---

## Task 1: Remove dead `activePanel` state and simplify `SummaryCards` (item 6)

**Files:**
- Modify: `frontend/src/pages/CommandDashboardPage.tsx:37` (state), `:136`
  (handler), `:241` (usage)
- Modify: `frontend/src/components/SummaryCards.tsx` (drop `onCardClick` prop)
- Test: `frontend/src/pages/CommandDashboardPage.test.tsx` (extend existing
  file)

**Interfaces:**
- Produces: `SummaryCards({ data }: { data: SummaryCardsData | null })` — the
  `onCardClick` prop is removed entirely; later tasks in this plan do not
  depend on it.

**Confirmation of dead code (from reading the source, not assumed):**
`CommandDashboardPage.tsx` renders every panel unconditionally inside
`<details open>` (line 243) — `_activePanel` is set by `handleCardClick` but
never read anywhere in the component to control rendering, scrolling, or
filtering. `SummaryCards.tsx`'s three `<button onClick={() =>
onCardClick("...")}>` wrappers (lines 14, 18, 23) call `onCardClick` but the
only consumer of that callback (`handleCardClick`) does nothing observable.
This is confirmed dead UI wiring, safe to remove.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/CommandDashboardPage.test.tsx` (the file already
mocks `SummaryCards` as `default: () => <div data-testid="summary-cards" />`
at line 35 — replace that mock's inline component with an import assertion
instead, since we're about to change the real component's prop signature and
want to catch a stale prop reference):

```tsx
import SummaryCards from "../components/SummaryCards";

describe("SummaryCards", () => {
  it("renders without an onCardClick prop", () => {
    render(<SummaryCards data={{ approvals_pending: 1, upcoming_duties_7d: 2, unfilled_gaps: 0, alerts_count: 0 }} />);
    expect(screen.getByTestId("summary-cards")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- CommandDashboardPage.test.tsx`
Expected: FAIL with a TypeScript/prop-types complaint or a runtime error,
because `SummaryCards` currently requires `onCardClick` and the test omits it
— `npm test` runs Vitest, which type-checks via esbuild-transform only (no
strict prop enforcement at runtime), so the more reliable failure signal here
is `npm run typecheck` reporting `Property 'onCardClick' is missing in type
'{ data: ... }' but required in type 'Props'.` Run both:
`cd frontend && npm run typecheck`
Expected: FAIL — `error TS2741: Property 'onCardClick' is missing in type ... on SummaryCards`

- [ ] **Step 3: Remove the dead state/handler in `CommandDashboardPage.tsx` and drop the prop from `SummaryCards.tsx`**

In `frontend/src/pages/CommandDashboardPage.tsx`, delete line 37:

```tsx
  const [_activePanel, setActivePanel] = useState<string>("summary");
```

Delete line 136:

```tsx
  const handleCardClick = (panel: string) => setActivePanel(panel);
```

Change line 241 from:

```tsx
        <SummaryCards data={summaryData} onCardClick={handleCardClick} />
```

to:

```tsx
        <SummaryCards data={summaryData} />
```

Since `useState` is still used elsewhere on the page? Check: this page has no
other `useState` call (verified by reading the full file — the only
`useState` import usage was `_activePanel`). Update the import on line 1 from:

```tsx
import { useState, useCallback, useMemo } from "react";
```

to:

```tsx
import { useCallback, useMemo } from "react";
```

In `frontend/src/components/SummaryCards.tsx`, replace the whole file:

```tsx
import { useTranslation } from "react-i18next";
import type { SummaryCards as SummaryCardsData } from "../api/commanderDashboard";

interface Props {
  data: SummaryCardsData | null;
}

export default function SummaryCards({ data }: Props) {
  const { t } = useTranslation();
  if (!data) return null;
  return (
    <div className="flex gap-4 mb-6" data-testid="summary-cards">
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-right" data-testid="card-approvals">
        <div className="text-2xl font-bold">{data.approvals_pending}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.approvals_pending")}</div>
      </div>
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-right" data-testid="card-upcoming">
        <div className="text-2xl font-bold">{data.upcoming_duties_7d}</div>
        {data.unfilled_gaps > 0 && <span className="text-xs text-red-500 mr-1">({data.unfilled_gaps} {t("command_dashboard.gaps")})</span>}
        <div className="text-sm text-gray-500">{t("command_dashboard.upcoming_7d")}</div>
      </div>
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-right" data-testid="card-alerts">
        <div className="text-2xl font-bold">{data.alerts_count}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.alerts")}</div>
      </div>
    </div>
  );
}
```

In `frontend/src/pages/CommandDashboardPage.test.tsx`, the mock at line 35
already renders a static `<div data-testid="summary-cards" />` regardless of
props, so it does not need to change for the existing test to keep passing.
Add the new `describe("SummaryCards", ...)` block from Step 1 to the bottom of
the file, using the **real** (unmocked) `SummaryCards` import — add this
import at the top of the test file alongside the existing imports:

```tsx
import SummaryCards from "../components/SummaryCards";
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no missing-prop error)

Run: `cd frontend && npm test -- CommandDashboardPage.test.tsx`
Expected: PASS (2 tests: the existing one + the new `SummaryCards` one)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/CommandDashboardPage.tsx frontend/src/components/SummaryCards.tsx frontend/src/pages/CommandDashboardPage.test.tsx
git commit -m "fix: remove dead activePanel state and unused SummaryCards onCardClick prop"
```

---

## Task 2: Replace the dashboard's full `HierarchyTree` panel with a read-only summary + link to `/team` (item 6)

**Files:**
- Modify: `frontend/src/pages/CommandDashboardPage.tsx` (imports, panel
  content around old lines 173-182)
- Modify: `frontend/src/i18n/he.json` (add two `command_dashboard.*` keys)
- Test: `frontend/src/pages/CommandDashboardPage.test.tsx` (extend)

**Interfaces:**
- Consumes (existing, unchanged): `getDashboardSoldiers(): Promise<SoldierWithStatus[]>`
  from `frontend/src/api/commanderDashboard.ts` (already fetched on this page
  as `soldiersQuery`/`soldiers` for `EntriesExitsPanel`); `NodeDTO[]` from
  `fetchFullTree` (already fetched as `nodesQuery`/`nodes`, still needed by
  `myNodes` for the calendar and own-potential panels).
- Produces: nothing new consumed by later tasks.

**Confirmation `/team` is a superset (from reading `TeamHierarchyPage.tsx`):**
`frontend/src/pages/TeamHierarchyPage.tsx:94` renders
`<HierarchyTree nodes={nodes} soldiers={soldiers} onChanged={refresh}
canManageLevelTypes={canManageLevelTypes} />` — the identical component with
full management (add child/soldier, assign commander, rename, delete — see
`frontend/src/components/HierarchyTree.tsx` lines 212-237) plus a soldier
table below it with onboard/edit/reset-password/remove actions (lines 96-213).
Nothing rendered by the dashboard's "soldiers" panel today is unavailable on
`/team`.

**Confirmation `soldierDTOs`/`listSoldiers`/`HierarchyTree` import become
unused after this change (from reading the full file):** `nodes` (from
`fetchFullTree`/`nodesQuery`) is still consumed by `myNodes` (line 111-114),
which feeds the calendar panel (line 171) and the `own_potential` panel (lines
204-234) — `nodesQuery`/`fetchFullTree`/`nodes` must stay. `soldierDTOs` (from
`listSoldiers`/`soldierDTOsQuery`) and the `HierarchyTree` import, by
contrast, are used **only** inside the panel being replaced (line 179) — no
other panel or hook on the page reads `soldierDTOs`. They are removed. The
page's own `soldiers` variable (from `getDashboardSoldiers`/`soldiersQuery`,
already fetched at line 42-43 for `EntriesExitsPanel`) is reused for the new
summary instead of fetching a second, broader soldier list.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/CommandDashboardPage.test.tsx`, inside the existing
`describe("CommandDashboardPage", ...)` block (after the existing `it(...)`):

```tsx
  it("shows a read-only soldier-count summary and a link to /team instead of the full hierarchy tree", async () => {
    renderPage();

    const panel = await screen.findByTestId("panel-soldiers");
    expect(within(panel).queryByTestId("hierarchy-tree")).not.toBeInTheDocument();
    expect(within(panel).getByTestId("soldiers-summary")).toBeInTheDocument();
    const link = within(panel).getByTestId("soldiers-panel-team-link");
    expect(link).toHaveAttribute("href", "/team");
  });
```

Add `within` to the existing `@testing-library/react` import at the top of the
file (currently `import { render, screen, waitFor } from
"@testing-library/react";`):

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
```

This test file renders `CommandDashboardPage` without a `MemoryRouter` (see
`renderPage()`, line 65-68) — a `<Link>` from `react-router-dom` needs a
router context to render, so wrap the render in one. Update `renderPage()`:

```tsx
import { MemoryRouter } from "react-router-dom";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}><CommandDashboardPage /></QueryClientProvider>
    </MemoryRouter>,
  );
}
```

Also update the `../api/commanderDashboard` mock (line 49-53) to return a
non-empty `getDashboardSoldiers` result so the summary has something to count,
and add the two new i18n keys to the existing `react-i18next` mock's key map
(after the `"command_dashboard.soldiers"` entry):

```tsx
vi.mock("../api/commanderDashboard", () => ({
  getSummary: vi.fn().mockResolvedValue({}),
  getDashboardSoldiers: vi.fn().mockResolvedValue([
    { id: "sol-1", personal_number: "1", full_name: "א", role: "soldier", hierarchy_node_id: "node-1", status: "active", cumulative_score: "0", normalised_score: "0", enrolled_at: "2026-01-01", left_at: null },
  ]),
  getFairnessInternal: vi.fn().mockResolvedValue(null), getFairnessExternal: vi.fn().mockResolvedValue(null),
  getPotential: vi.fn().mockResolvedValue(null), getUpcoming: vi.fn().mockResolvedValue(null), getAlerts: vi.fn().mockResolvedValue([]),
}));
```

(Replace the existing `vi.mock("../api/commanderDashboard", ...)` block
entirely with the one above — it is the same block with `getDashboardSoldiers`
changed from `vi.fn().mockResolvedValue([])` to the one-row payload.)

```tsx
      "command_dashboard.soldiers": "חיילים",
      "command_dashboard.soldiers_count": "{{count}} חיילים בפיקוד",
      "command_dashboard.go_to_team": "מעבר לניהול הצוות",
```

(Insert these two new lines directly after the existing
`"command_dashboard.soldiers": "חיילים",` line inside the `react-i18next`
mock's key map.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- CommandDashboardPage.test.tsx`
Expected: FAIL — `hierarchy-tree` testid is still present (the panel still
renders `HierarchyTree`) and/or `soldiers-summary`/`soldiers-panel-team-link`
are not found.

- [ ] **Step 3: Replace the panel content and the imports**

In `frontend/src/pages/CommandDashboardPage.tsx`, remove these three now-dead
imports (lines 16, 18, 19):

```tsx
import HierarchyTree from "../components/HierarchyTree";
```
```tsx
import { fetchFullTree } from "../api/hierarchy";
import { listSoldiers } from "../api/soldiers";
```

replacing the `fetchFullTree` line with (keep `fetchFullTree` — only
`listSoldiers` and the `HierarchyTree` import are dropped):

```tsx
import { fetchFullTree } from "../api/hierarchy";
```

Add a `Link` import from `react-router-dom` near the top with the other
framework imports:

```tsx
import { Link } from "react-router-dom";
```

Remove the now-unused soldier-DTO query (old lines 48-49):

```tsx
  const soldierDTOsQuery = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const soldierDTOs = soldierDTOsQuery.data ?? [];
```

Add a memoized per-node soldier breakdown, placed directly after the existing
`myNodes` `useMemo` (after old line 114):

```tsx
  const soldiersByNode = useMemo(() => {
    const nodeNameById = new Map(nodes.map((n) => [n.id, n.name]));
    const counts = new Map<string, number>();
    for (const s of soldiers) {
      const label = s.hierarchy_node_id ? (nodeNameById.get(s.hierarchy_node_id) ?? t("command_dashboard.node")) : t("command_dashboard.node");
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([nodeName, count]) => ({ nodeName, count }));
  }, [nodes, soldiers, t]);
```

Replace the "soldiers" panel's `content` (old lines 173-183):

```tsx
    {
      id: "soldiers",
      title: t("command_dashboard.soldiers"),
      content: (
        <div>
          <div className="mb-4">
            <HierarchyTree nodes={nodes} soldiers={soldierDTOs} canManageLevelTypes={false} onChanged={refresh} />
          </div>
        </div>
      ),
    },
```

with:

```tsx
    {
      id: "soldiers",
      title: t("command_dashboard.soldiers"),
      content: (
        <div data-testid="soldiers-summary">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {t("command_dashboard.soldiers_count", { count: soldiers.length })}
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {soldiersByNode.map(({ nodeName, count }) => (
              <li key={nodeName} className="flex justify-between border-b border-gray-100 dark:border-gray-700 py-1">
                <span>{nodeName}</span>
                <span className="text-gray-500 dark:text-gray-400">{count}</span>
              </li>
            ))}
          </ul>
          <Link
            to="/team"
            className="inline-block mt-3 text-indigo-600 dark:text-indigo-300 hover:underline"
            data-testid="soldiers-panel-team-link"
          >
            {t("command_dashboard.go_to_team")}
          </Link>
        </div>
      ),
    },
```

In `frontend/src/i18n/he.json`, add the two new keys inside the
`"command_dashboard"` object, directly after `"soldiers": "רשימת חיילים",`
(around line 980):

```json
    "soldiers": "רשימת חיילים",
    "soldiers_count": "{{count}} חיילים בפיקוד",
    "go_to_team": "מעבר לניהול הצוות",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- CommandDashboardPage.test.tsx`
Expected: PASS (3 tests total)

Run: `cd frontend && npm run lint`
Expected: PASS — zero warnings (this catches the now-unused `listSoldiers`/
`HierarchyTree` imports if either was missed)

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/CommandDashboardPage.tsx frontend/src/pages/CommandDashboardPage.test.tsx frontend/src/i18n/he.json
git commit -m "fix: replace dashboard hierarchy-tree panel with read-only summary + /team link"
```

---

## Task 3: Commander-dashboard upcoming feeds include `algorithm_draft` (item 14, part 1)

**Files:**
- Modify: `backend/app/services/commander_dashboard.py:140-152` (`summary_cards`
  upcoming count), `:296-360` (`upcoming_duties`)
- Modify: `backend/app/routes/commander_dashboard.py:62-77` (`UpcomingAssignment`
  Pydantic model)
- Modify: `frontend/src/api/commanderDashboard.ts:44-59` (`UpcomingAssignment`
  TS interface)
- Modify: `frontend/src/components/UpcomingSnapshot.tsx` (draft badge)
- Test: `backend/app/services/tests/test_commander_dashboard.py`
- Test: `backend/app/routes/tests/test_commander_dashboard.py`
- Test: `frontend/src/components/UpcomingSnapshot.test.tsx` (create — no such
  file exists yet; verified via `Glob`)

**Interfaces:**
- Produces: `commander_dashboard.upcoming_duties(session, *, subtree_ids, days) -> list[dict]`
  — same shape as before, plus a new `"status"` key per assignment dict
  (`"published"` or `"algorithm_draft"`).
- Produces: `UpcomingAssignment` (Pydantic, `backend/app/routes/commander_dashboard.py`)
  gains `status: str`.
- Produces: `UpcomingAssignment` (TS, `frontend/src/api/commanderDashboard.ts`)
  gains `status: string`.

- [ ] **Step 1: Write the failing backend service test**

Add to `backend/app/services/tests/test_commander_dashboard.py`:

```python
from app.services.commander_dashboard import upcoming_duties


def test_upcoming_duties_includes_algorithm_draft(admin_session):
    from datetime import date as _date
    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="upcoming_draft_test")
    soldier = create_soldier(admin_session, personal_number="7940001", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_upcoming_draft_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_upcoming_draft_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=_date.today(),
            end_date=_date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    days = upcoming_duties(admin_session, subtree_ids=[node.id], days=7)
    all_assignments = [a for day in days for a in day["assignments"]]
    assert len(all_assignments) == 1
    assert all_assignments[0]["status"] == "algorithm_draft"


def test_summary_cards_upcoming_count_includes_algorithm_draft(admin_session):
    from datetime import date as _date
    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="summary_draft_test")
    soldier = create_soldier(admin_session, personal_number="7940002", hierarchy_node_id=node.id)
    baseline = summary_cards(admin_session, subtree_ids=[node.id])

    dt = DutyType(name="dt_summary_draft_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_summary_draft_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=_date.today(),
            end_date=_date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    cards = summary_cards(admin_session, subtree_ids=[node.id])
    assert cards["upcoming_duties_7d"] == baseline["upcoming_duties_7d"] + 1
```

Add the required new imports at the top of the file (the file already imports
`Decimal`; add `timedelta`):

```python
from datetime import date, timedelta
```

(This replaces the existing `from datetime import date` line — check first
with the file's current imports, since `date` is already imported at line 3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest app/services/tests/test_commander_dashboard.py -k "algorithm_draft" -v`
Expected: FAIL — `test_upcoming_duties_includes_algorithm_draft` gets 0
assignments back (the draft is filtered out by the current `status ==
"published"` clause); `test_summary_cards_upcoming_count_includes_algorithm_draft`
asserts a count that's one too high.

- [ ] **Step 3: Widen the two status filters and add the `status` field**

In `backend/app/services/commander_dashboard.py`, change the `summary_cards`
upcoming-assignments query (current lines 140-151):

```python
    upcoming_assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= next_week,
                DutyAssignment.end_date > today,
            )
        )
        .scalars()
        .all()
    )
```

to:

```python
    upcoming_assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= next_week,
                DutyAssignment.end_date > today,
            )
        )
        .scalars()
        .all()
    )
```

Change the `upcoming_duties` assignments query (current lines 302-313):

```python
    assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= end,
                DutyAssignment.end_date >= today,
            )
        )
        .scalars()
        .all()
    )
```

to:

```python
    assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= end,
                DutyAssignment.end_date >= today,
            )
        )
        .scalars()
        .all()
    )
```

Add `"status": a.status,` to the per-assignment dict built in the loop below
(current lines 337-353), directly after the `"is_reserve": a.is_reserve,` line:

```python
                    "node_name": node.name if node else "",
                    "is_reserve": a.is_reserve,
                    "status": a.status,
                }
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest app/services/tests/test_commander_dashboard.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Write the failing route-level test**

Add to `backend/app/routes/tests/test_commander_dashboard.py` (check the
file's existing imports/fixtures first — it uses a `client`/`admin_session`
pattern matching `test_soldiers_api.py`):

```python
def test_upcoming_route_includes_status_field_for_draft(client, admin_session):
    from datetime import date, timedelta
    from decimal import Decimal
    from app.db.models import DutyAssignment, DutyLocation, DutyType
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="unit", name="upcoming_route_draft_test")
    cmd = create_soldier(admin_session, personal_number="7940101", role="commander")
    node.commander_id = cmd.id
    soldier = create_soldier(admin_session, personal_number="7940102", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_upcoming_route_draft", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_upcoming_route_draft")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    r = client.get("/api/command-dashboard/upcoming", headers=auth_headers(cmd))
    assert r.status_code == 200
    all_assignments = [a for day in r.json() for a in day["assignments"]]
    assert len(all_assignments) == 1
    assert all_assignments[0]["status"] == "algorithm_draft"
```

- [ ] **Step 6: Run the route test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest app/routes/tests/test_commander_dashboard.py -k draft -v`
Expected: FAIL — `KeyError: 'status'` or a `ResponseValidationError` (the
`UpcomingAssignment` Pydantic model doesn't declare `status` yet, so FastAPI's
response model would silently drop the field the service now returns — the
test's `all_assignments[0]["status"]` lookup fails with `KeyError`).

- [ ] **Step 7: Add `status` to the `UpcomingAssignment` Pydantic model**

In `backend/app/routes/commander_dashboard.py`, change the `UpcomingAssignment`
class (current lines 62-76):

```python
class UpcomingAssignment(BaseModel):
    assignment_id: str
    soldier_id: uuid.UUID
    soldier_name: str
    duty_type_id: str
    duty_type_name: str
    duty_location_id: uuid.UUID
    duty_location_name: str
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    shift_id: uuid.UUID | None
    node_name: str
    is_reserve: bool
```

to:

```python
class UpcomingAssignment(BaseModel):
    assignment_id: str
    soldier_id: uuid.UUID
    soldier_name: str
    duty_type_id: str
    duty_type_name: str
    duty_location_id: uuid.UUID
    duty_location_name: str
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    shift_id: uuid.UUID | None
    node_name: str
    is_reserve: bool
    status: str
```

- [ ] **Step 8: Run the route test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest app/routes/tests/test_commander_dashboard.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 9: Add `status` to the frontend `UpcomingAssignment` interface and render a draft badge**

In `frontend/src/api/commanderDashboard.ts`, change the `UpcomingAssignment`
interface (current lines 44-59):

```ts
export interface UpcomingAssignment {
  assignment_id: string;
  soldier_id: string;
  soldier_name: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_location_id: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  shift_id: string | null;
  node_name: string;
  is_reserve: boolean;
}
```

to:

```ts
export interface UpcomingAssignment {
  assignment_id: string;
  soldier_id: string;
  soldier_name: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_location_id: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  shift_id: string | null;
  node_name: string;
  is_reserve: boolean;
  status: string;
}
```

In `frontend/src/components/UpcomingSnapshot.tsx`, the `Badge` component
(current lines 22-32) renders `a.soldier_name`. Add a draft indicator reusing
the existing `duty_history.draft_badge` i18n key already used for the same
purpose in `frontend/src/components/DutyHistoryPanel.tsx:214`. Add
`useTranslation`'s `t` (already imported and used elsewhere in this file via
`const { t } = useTranslation();` at line 34 inside the default export — the
`Badge` sub-component does not currently receive `t`, so pass it as a prop).
Change `Badge` from:

```tsx
function Badge({ a, onSelect }: { a: UpcomingAssignment; onSelect: (a: UpcomingAssignment) => void }) {
  return (
    <button
      onClick={() => onSelect(a)}
      className={`text-xs rounded px-2 py-0.5 cursor-pointer border ${
        a.is_reserve ? "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800" : "bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600"
      }`}
    >
      {a.soldier_name || a.duty_type_id?.slice(0, 6) || "?"}
    </button>
  );
}
```

to:

```tsx
function Badge({ a, onSelect, t }: { a: UpcomingAssignment; onSelect: (a: UpcomingAssignment) => void; t: (key: string) => string }) {
  return (
    <button
      onClick={() => onSelect(a)}
      className={`text-xs rounded px-2 py-0.5 cursor-pointer border ${
        a.is_reserve ? "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800" : "bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600"
      }`}
    >
      {a.status === "algorithm_draft" && (
        <span className="mr-1 px-1 rounded bg-blue-100 text-blue-800" data-testid={`draft-badge-${a.assignment_id}`}>
          {t("duty_history.draft_badge")}
        </span>
      )}
      {a.soldier_name || a.duty_type_id?.slice(0, 6) || "?"}
    </button>
  );
}
```

Update the call site inside `UpcomingSnapshot` (current line 83, inside the
`.map((a) => <Badge key={a.assignment_id} a={a} onSelect={setSelected} />)`):

```tsx
                day.assignments.map((a) => <Badge key={a.assignment_id} a={a} onSelect={setSelected} t={t} />)
```

- [ ] **Step 10: Write the failing frontend test**

Create `frontend/src/components/UpcomingSnapshot.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import UpcomingSnapshot from "./UpcomingSnapshot";
import type { UpcomingDay } from "../api/commanderDashboard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({ "duty_history.draft_badge": "טיוטה", "command_dashboard.no_upcoming": "אין תורנויות קרובות" }[key] ?? key),
  }),
}));
vi.mock("../hooks/usePublicSettings", () => ({ usePublicSettings: () => ({}) }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));

function makeDay(status: string): UpcomingDay {
  return {
    date: "2026-08-20",
    assignments: [
      {
        assignment_id: "a1", soldier_id: "s1", soldier_name: "חייל בדיקה",
        duty_type_id: "dt1", duty_type_name: "שמירה",
        duty_location_id: "loc1", duty_location_name: "שער",
        start_date: "2026-08-20", end_date: "2026-08-21",
        start_time: "08:00", end_time: "08:00",
        shift_id: null, node_name: "יחידה", is_reserve: false, status,
      },
    ],
  };
}

describe("UpcomingSnapshot", () => {
  it("shows a draft badge for an algorithm_draft assignment", () => {
    render(<UpcomingSnapshot data={[makeDay("algorithm_draft")]} />);
    expect(screen.getByTestId("draft-badge-a1")).toBeInTheDocument();
  });

  it("shows no draft badge for a published assignment", () => {
    render(<UpcomingSnapshot data={[makeDay("published")]} />);
    expect(screen.queryByTestId("draft-badge-a1")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 11: Confirm the red bar, then re-apply the fix**

Temporarily comment out the `{a.status === "algorithm_draft" && (...)}` block
added to `Badge` in Step 9 (leave everything else from Step 9 in place) and
run:

Run: `cd frontend && npm test -- UpcomingSnapshot.test.tsx`
Expected: FAIL — `TestingLibraryElementError: Unable to find an element by:
[data-testid="draft-badge-a1"]` for the "shows a draft badge" test.

Then uncomment the block, restoring Step 9's edit exactly as written.

- [ ] **Step 12: Run all new/changed tests to verify they pass**

Run: `cd frontend && npm test -- UpcomingSnapshot.test.tsx`
Expected: PASS (2 tests)

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/commander_dashboard.py backend/app/services/tests/test_commander_dashboard.py backend/app/routes/commander_dashboard.py backend/app/routes/tests/test_commander_dashboard.py frontend/src/api/commanderDashboard.ts frontend/src/components/UpcomingSnapshot.tsx frontend/src/components/UpcomingSnapshot.test.tsx
git commit -m "feat: include algorithm_draft assignments in commander-dashboard upcoming feeds"
```

---

## Task 4: Extract a parameterized span-builder in `scoring.py` without changing `effective_duty_spans`'s behavior (item 14, part 2)

**Files:**
- Modify: `backend/app/services/scoring.py:108-201` (`effective_duty_spans`)
- Test: `backend/app/services/tests/test_scoring_dismissal.py` or
  `backend/tests/unit/test_scoring_service.py` (check which file already
  covers `effective_duty_spans` directly via `Glob`/`Grep` before choosing —
  use whichever already imports and calls `effective_duty_spans`, to keep the
  new regression test next to its siblings)

**Interfaces:**
- Produces: `_effective_duty_spans_impl(session, *, statuses: list[str], soldier_ids: set[uuid.UUID] | None = None, date_from: date | None = None, date_to: date | None = None) -> list[dict[str, Any]]`
  — identical span-dict shape as today's `effective_duty_spans`, plus a new
  `"status"` key holding the source assignment's `status` string.
- Produces: `effective_duty_spans(session, *, soldier_ids=None, date_from=None, date_to=None) -> list[dict[str, Any]]`
  — **unchanged signature and behavior**; internally now calls
  `_effective_duty_spans_impl(session, statuses=["published"], soldier_ids=soldier_ids, date_from=date_from, date_to=date_to)`.
- Produces: `effective_duty_spans_with_drafts(session, *, soldier_ids=None, date_from=None, date_to=None) -> list[dict[str, Any]]`
  — calls `_effective_duty_spans_impl(session, statuses=["published", "algorithm_draft"], soldier_ids=soldier_ids, date_from=date_from, date_to=date_to)`.
  Consumed by Task 5's route change; never consumed by any scoring/effort/
  fairness function.

- [ ] **Step 1: Locate the existing direct test coverage for `effective_duty_spans`**

Run: `cd backend && grep -rn "effective_duty_spans" app/services/tests backend/tests 2>/dev/null` (from repo root:
`grep -rln "effective_duty_spans" backend/app/services/tests backend/tests`)
to find the file(s) already calling it directly. Add the new tests below to
that file (do not create a new file if one already exercises this function).

- [ ] **Step 2: Write the failing regression test**

Add to the file identified in Step 1 (adjust the helper imports —
`create_node`, `create_soldier` from `tests.helpers`, and whatever session
fixture that file already uses, e.g. `admin_session` — to match that file's
existing pattern exactly):

```python
def test_effective_duty_spans_never_includes_algorithm_draft(admin_session):
    from datetime import date, timedelta
    from decimal import Decimal
    from app.db.models import DutyAssignment, DutyLocation, DutyType
    from app.services.scoring import effective_duty_spans

    node = create_node(admin_session, level="unit", name="eds_no_draft_test")
    soldier = create_soldier(admin_session, personal_number="7950001", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_eds_no_draft", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_eds_no_draft")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date.today(), end_date=date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    spans = effective_duty_spans(admin_session, soldier_ids={soldier.id})
    assert spans == []


def test_effective_duty_spans_with_drafts_includes_algorithm_draft(admin_session):
    from datetime import date, timedelta
    from decimal import Decimal
    from app.db.models import DutyAssignment, DutyLocation, DutyType
    from app.services.scoring import effective_duty_spans_with_drafts

    node = create_node(admin_session, level="unit", name="eds_with_draft_test")
    soldier = create_soldier(admin_session, personal_number="7950002", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_eds_with_draft", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_eds_with_draft")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date.today(), end_date=date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    spans = effective_duty_spans_with_drafts(admin_session, soldier_ids={soldier.id})
    assert len(spans) == 1
    assert spans[0]["status"] == "algorithm_draft"
    assert spans[0]["soldier_id"] == soldier.id
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest <path-to-file-from-Step-1> -k "eds_no_draft or eds_with_draft" -v`
Expected: `test_effective_duty_spans_never_includes_algorithm_draft` PASSES
already (current behavior is correctly published-only — this confirms the
baseline before refactoring); `test_effective_duty_spans_with_drafts_includes_algorithm_draft`
FAILS with `ImportError: cannot import name 'effective_duty_spans_with_drafts'`.

- [ ] **Step 4: Extract `_effective_duty_spans_impl` and add the two wrappers**

In `backend/app/services/scoring.py`, replace the `effective_duty_spans`
function (current lines 108-201) with:

```python
def _effective_duty_spans_impl(
    session: Session,
    *,
    statuses: list[str],
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Shared implementation behind `effective_duty_spans` (statuses=["published"],
    the scoring/effort/fairness source of truth — never widen its caller-visible
    contract to include drafts) and `effective_duty_spans_with_drafts`
    (statuses=["published", "algorithm_draft"], display surfaces only).
    Assignments matching `statuses` are expanded per day with overrides applied,
    then re-merged into contiguous runs where the effective soldier is
    unchanged. Degrades to the original block when there are no overrides;
    cancelled days (NULL effective) break runs and are dropped. Optionally
    filtered to soldier_ids and to spans overlapping [date_from, date_to]."""
    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status.in_(statuses)))
        .scalars()
        .all()
    )
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    dismissal_ranges: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for d in session.execute(select(DutyDismissal)).scalars().all():
        dismissal_ranges.setdefault(d.duty_assignment_id, []).append((d.dismissed_from, d.dismissed_to))

    def _is_dismissed(assignment_id: uuid.UUID, day: date) -> bool:
        return any(df <= day <= dt for df, dt in dismissal_ranges.get(assignment_id, []))

    spans: list[dict[str, Any]] = []
    for a in assignments:
        last_assignment_day = a.end_date - timedelta(days=1)

        def _make_span(cur: Any, run_start: date, run_end: date, *, _a: DutyAssignment = a) -> dict[str, Any]:
            # A run only carries the assignment's real clock time on the edge
            # day(s) that match the assignment's own boundaries; a run that
            # was split off mid-assignment by an override has no wall-clock
            # time of its own, so it degrades to a full calendar day there.
            start_time = _a.start_time if run_start == _a.start_date else "00:00"
            end_time = _a.end_time if run_end == last_assignment_day else "23:59"
            original_owner = cur == _a.soldier_id
            return {
                "assignment_id": _a.id,
                "soldier_id": cur,
                "duty_type_id": _a.duty_type_id,
                "duty_location_id": _a.duty_location_id,
                "start_date": run_start,
                # Exclusive, matching DutyAssignment/DutyShift's own convention
                # (run_end above is the run's last INCLUSIVE day).
                "end_date": run_end + timedelta(days=1),
                "start_time": start_time,
                "end_time": end_time,
                "start_at": combine_date_time(run_start, start_time),
                "end_at": combine_date_time(run_end, end_time),
                "shift_id": _a.duty_shift_id,
                "is_reserve": _a.is_reserve,
                "called_up_from": _a.called_up_from,
                "called_up_to": _a.called_up_to,
                "weapon_ineligible": _a.weapon_ineligible if original_owner else False,
                "weapon_ineligible_reason": _a.weapon_ineligible_reason if original_owner else None,
                "status": _a.status,
            }

        cur: object = _UNSET
        run_start: date | None = None
        run_end: date | None = None
        day = a.start_date
        while day < a.end_date:
            ov = overrides.get((a.id, day))
            if ov is not None:
                eff = ov.effective_soldier_id
            elif _is_dismissed(a.id, day):
                eff = None
            else:
                eff = a.soldier_id
            if eff == cur:
                run_end = day
            else:
                if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
                    spans.append(_make_span(cur, run_start, run_end))
                cur = eff
                run_start = day if eff is not None else None
                run_end = day if eff is not None else None
            day += timedelta(days=1)
        if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
            spans.append(_make_span(cur, run_start, run_end))
    result: list[dict[str, Any]] = []
    for sp in spans:
        if soldier_ids is not None and sp["soldier_id"] not in soldier_ids:
            continue
        if date_from is not None and sp["end_date"] <= date_from:
            continue
        if date_to is not None and sp["start_date"] > date_to:
            continue
        result.append(sp)
    result.sort(key=lambda s: s["start_date"])
    return result


def effective_duty_spans(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Published assignments only — the scoring/effort/fairness source of
    truth. Do not widen this function's status filter; add a new function
    (see `effective_duty_spans_with_drafts`) for any display surface that
    needs drafts."""
    return _effective_duty_spans_impl(
        session, statuses=["published"], soldier_ids=soldier_ids, date_from=date_from, date_to=date_to,
    )


def effective_duty_spans_with_drafts(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Published + algorithm_draft assignments, for display surfaces only
    (e.g. a soldier's own upcoming-duties widget). Never call this from
    scoring, effort, or fairness code — use `effective_duty_spans` there."""
    return _effective_duty_spans_impl(
        session, statuses=["published", "algorithm_draft"], soldier_ids=soldier_ids, date_from=date_from, date_to=date_to,
    )
```

Note the closure fix: the original `_make_span` closed over the loop variable
`a` by reference (safe in the original code only because `_make_span` was
always fully consumed — appended to `spans` — before the next loop iteration
rebound `a`). The extracted version adds `_a: DutyAssignment = a` as a default
argument to bind each call to the specific assignment instance defensively;
behavior is unchanged (default-argument binding happens at function
definition time, matching what happened implicitly before), this only makes
the existing safety explicit while the function moves to a shared helper.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest <path-to-file-from-Step-1> -k "eds_no_draft or eds_with_draft" -v`
Expected: PASS (both tests)

Run: `cd backend && .venv/Scripts/pytest -m scoring -q`
Expected: PASS — this is the full existing scoring-marked test suite,
confirming the refactor didn't change `effective_duty_spans`'s observable
behavior for any existing caller (`shift_count_by_soldier`,
`duty_score_by_soldier`'s sibling functions, `transparency_rows`, etc., which
this task does not modify).

Run: `cd backend && .venv/Scripts/pytest -m duty -q`
Expected: PASS — covers `backend/app/routes/tests/test_assignments.py` and
similar, which exercise `GET /assignments/effective` (`list_effective_duties`
in `backend/app/routes/assignments.py`), the route that unpacks
`EffectiveDutyOut(**sp, ...)` from each span dict — confirm the new `"status"`
key on every span doesn't break that route yet (it doesn't: FastAPI/Pydantic
response models silently drop unrecognized dict keys passed via `**sp` unless
the field is declared, so this is a no-op until Task 5 declares it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scoring.py <path-to-file-from-Step-1>
git commit -m "refactor: extract parameterized _effective_duty_spans_impl; add draft-inclusive display wrapper"
```

---

## Task 5: `GET /assignments/effective` gains an opt-in `include_drafts` flag; `HomePage`'s upcoming-duties widget uses it (item 14, part 3)

**Files:**
- Modify: `backend/app/routes/assignments.py:56-70` (`EffectiveDutyOut`),
  `:131-149` (`list_effective_duties`)
- Modify: `frontend/src/api/assignments.ts:16-42` (`EffectiveDuty`,
  `listEffectiveDuties`)
- Modify: `frontend/src/pages/HomePage.tsx:73` (query call)
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`
  (draft badge)
- Test: `backend/tests/integration/test_assignments_api.py`
- Test: `frontend/src/components/dashboard/UpcomingDutiesWidget.test.tsx`
  (extend existing file)

**Interfaces:**
- Consumes: `scoring_svc.effective_duty_spans` / `scoring_svc.effective_duty_spans_with_drafts`
  from Task 4.
- Produces: `GET /assignments/effective?soldier_id=&date_from=&date_to=&include_drafts=` —
  `include_drafts` defaults to `false`; unchanged behavior for every existing
  caller that doesn't pass it.
- Produces: `listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string; include_drafts?: boolean }): Promise<EffectiveDuty[]>`
  — the new `include_drafts` param is optional and additive; every existing
  call site (`AlertBanners.tsx`, `DutyHistoryPanel.tsx`, `OfferSwapModal.tsx`,
  `ShiftDetailPanel.tsx`, `MyDutiesPage.tsx`, `SwapsPage.tsx`) keeps calling
  without it and is unaffected.

- [ ] **Step 1: Write the failing backend integration test**

Add to `backend/tests/integration/test_assignments_api.py` (check its existing
imports/helpers first — it will already import `auth_headers`, `create_node`,
`create_soldier` from `tests.helpers`, matching the pattern used elsewhere in
this plan):

```python
def test_effective_duties_excludes_drafts_by_default_but_includes_with_flag(client, admin_session):
    from datetime import date, timedelta
    from decimal import Decimal
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    soldier = create_soldier(admin_session, personal_number="7960001")
    dt = DutyType(name="dt_eff_draft_flag", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_eff_draft_flag")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date.today(), end_date=date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    r_default = client.get(
        "/api/assignments/effective", params={"soldier_id": str(soldier.id)}, headers=auth_headers(soldier),
    )
    assert r_default.status_code == 200
    assert r_default.json() == []

    r_with_drafts = client.get(
        "/api/assignments/effective",
        params={"soldier_id": str(soldier.id), "include_drafts": "true"},
        headers=auth_headers(soldier),
    )
    assert r_with_drafts.status_code == 200
    assert len(r_with_drafts.json()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_assignments_api.py -k drafts_by_default -v`
Expected: FAIL — `422 Unprocessable Entity` (unrecognized query param
`include_drafts`) or the second call still returns `[]` since the route
doesn't branch on the flag yet.

- [ ] **Step 3: Add the `include_drafts` param and `status` field to the route**

In `backend/app/routes/assignments.py`, change the `EffectiveDutyOut` model
(current lines 56-70):

```python
class EffectiveDutyOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    start_at: datetime
    end_at: datetime
    shift_id: uuid.UUID | None = None
    is_reserve: bool = False
    called_up_from: date | None = None
    called_up_to: date | None = None
    weapon_ineligible: bool = False
    weapon_ineligible_reason: str | None = None
```

to:

```python
class EffectiveDutyOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    start_at: datetime
    end_at: datetime
    shift_id: uuid.UUID | None = None
    is_reserve: bool = False
    called_up_from: date | None = None
    called_up_to: date | None = None
    weapon_ineligible: bool = False
    weapon_ineligible_reason: str | None = None
    status: str = "published"
```

(A default of `"published"` keeps any other code constructing an
`EffectiveDutyOut` without a status literal working — but every span dict
from `_effective_duty_spans_impl` now always includes `"status"`, so the
default is only a defensive fallback.)

Change `list_effective_duties` (current lines 131-149):

```python
@router.get("/effective", response_model=list[EffectiveDutyOut])
def list_effective_duties(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EffectiveDutyOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    spans = scoring_svc.effective_duty_spans(
        session, soldier_ids={soldier_id}, date_from=date_from, date_to=date_to
    )
    type_ids = {sp["duty_type_id"] for sp in spans}
    names = {
        dt.id: dt.name
        for dt in session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars()
    } if type_ids else {}
    return [
        EffectiveDutyOut(**sp, duty_type_name=names.get(sp["duty_type_id"], ""))
        for sp in spans
    ]
```

to:

```python
@router.get("/effective", response_model=list[EffectiveDutyOut])
def list_effective_duties(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    include_drafts: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EffectiveDutyOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    span_fn = scoring_svc.effective_duty_spans_with_drafts if include_drafts else scoring_svc.effective_duty_spans
    spans = span_fn(session, soldier_ids={soldier_id}, date_from=date_from, date_to=date_to)
    type_ids = {sp["duty_type_id"] for sp in spans}
    names = {
        dt.id: dt.name
        for dt in session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars()
    } if type_ids else {}
    return [
        EffectiveDutyOut(**sp, duty_type_name=names.get(sp["duty_type_id"], ""))
        for sp in spans
    ]
```

No extra authorization is added beyond the existing `SOLDIER_READ` check:
unlike `GET /soldiers/{id}/duty-history`'s `include_drafts` (which exposes a
management-facing timeline of someone else's drafts and is restricted to
admin/DM), this flag only ever surfaces a soldier's **own** upcoming duties on
their personal home page (`s.id == user.id`, which skips the `authorize()`
call entirely) — seeing your own not-yet-published assignment is exactly
item 14's request, not a new information-disclosure surface.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_assignments_api.py -k drafts_by_default -v`
Expected: PASS

Run: `cd backend && .venv/Scripts/pytest -m duty -q`
Expected: PASS (full `duty`-marked suite, confirming no other
`/assignments/effective` caller broke)

- [ ] **Step 5: Wire the frontend API wrapper and `HomePage`**

In `frontend/src/api/assignments.ts`, change the `EffectiveDuty` interface
(current lines 16-34) to add `status`:

```ts
export interface EffectiveDuty {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  start_at: string;
  end_at: string;
  shift_id?: string | null;
  is_reserve: boolean;
  called_up_from: string | null;
  called_up_to: string | null;
  weapon_ineligible: boolean;
  weapon_ineligible_reason: string | null;
  status: string;
}
```

Change `listEffectiveDuties` (current lines 40-42):

```ts
export async function listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string }): Promise<EffectiveDuty[]> {
  return (await api.get<EffectiveDuty[]>(`/assignments/effective`, { params: { soldier_id: soldierId, ...params } })).data;
}
```

to:

```ts
export async function listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string; include_drafts?: boolean }): Promise<EffectiveDuty[]> {
  return (await api.get<EffectiveDuty[]>(`/assignments/effective`, { params: { soldier_id: soldierId, ...params } })).data;
}
```

In `frontend/src/pages/HomePage.tsx`, change the `listEffectiveDuties` call
(current line 73):

```tsx
    queryFn: () => listEffectiveDuties(user!.id, { date_from: offsetDate(-365), date_to: offsetDate(60) }),
```

to:

```tsx
    queryFn: () => listEffectiveDuties(user!.id, { date_from: offsetDate(-365), date_to: offsetDate(60), include_drafts: true }),
```

In `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`, add a draft
badge next to the duty-type name (current lines 58-63):

```tsx
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium text-sm">{typeNames[d.duty_type_id] ?? "—"}</div>
                    <div className={`text-xs mt-0.5 ${status.calledUp ? "text-amber-700 dark:text-amber-400 font-medium" : "text-gray-500 dark:text-gray-400"}`}>
                      {status.text}
                    </div>
                  </div>
                  <span className="text-gray-400 text-xs">›</span>
                </div>
```

to:

```tsx
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium text-sm">
                      {d.status === "algorithm_draft" && (
                        <span className="mr-1 text-[10px] px-1 rounded bg-blue-100 text-blue-800" data-testid={`draft-badge-${d.assignment_id}`}>
                          {t("duty_history.draft_badge")}
                        </span>
                      )}
                      {typeNames[d.duty_type_id] ?? "—"}
                    </div>
                    <div className={`text-xs mt-0.5 ${status.calledUp ? "text-amber-700 dark:text-amber-400 font-medium" : "text-gray-500 dark:text-gray-400"}`}>
                      {status.text}
                    </div>
                  </div>
                  <span className="text-gray-400 text-xs">›</span>
                </div>
```

(`t` is already destructured from `useTranslation()` at the top of this
component's default export — no new import needed.)

- [ ] **Step 6: Write the failing frontend test**

The file `frontend/src/components/dashboard/UpcomingDutiesWidget.test.tsx`
already exists (confirmed via `Glob`) with a `makeDuty()` helper. Add to it:

```tsx
  it("shows a draft badge for an algorithm_draft duty", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty({ status: "algorithm_draft" })]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.getByTestId(/draft-badge-/)).toBeInTheDocument();
  });

  it("shows no draft badge for a published duty", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty({ status: "published" })]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.queryByTestId(/draft-badge-/)).not.toBeInTheDocument();
  });
```

Check the file's existing `makeDuty()` factory — if it doesn't already set a
`status` field on the returned `EffectiveDuty`, add `status: "published"` to
its default return object so every pre-existing test in the file (which don't
pass `status` explicitly) keeps compiling against the now-required
`EffectiveDuty.status` field.

- [ ] **Step 7: Confirm the red bar, then re-apply the fix**

Temporarily comment out the `{d.status === "algorithm_draft" && (...)}` block
added to `UpcomingDutiesWidget.tsx` in Step 5 (leave the rest of Step 5's edit
in place) and run:

Run: `cd frontend && npm test -- UpcomingDutiesWidget.test.tsx`
Expected: FAIL — `TestingLibraryElementError: Unable to find an element by: [data-testid=/draft-badge-/]`
for the "shows a draft badge" test.

Then uncomment the block, restoring Step 5's edit exactly as written, and
run again:

Run: `cd frontend && npm test -- UpcomingDutiesWidget.test.tsx`
Expected: PASS (all tests in the file, existing + 2 new)

- [ ] **Step 8: Run full frontend verification**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/assignments.py backend/tests/integration/test_assignments_api.py frontend/src/api/assignments.ts frontend/src/pages/HomePage.tsx frontend/src/components/dashboard/UpcomingDutiesWidget.tsx frontend/src/components/dashboard/UpcomingDutiesWidget.test.tsx
git commit -m "feat: add opt-in include_drafts flag to /assignments/effective; show drafts on HomePage upcoming widget"
```

---

## Task 6: Duty-history command-scope regression coverage (item 16)

**Files:**
- Test: `frontend/src/components/UnifiedSoldierModal.test.tsx` (extend)

**Interfaces:**
- Consumes (existing, unchanged): `can_view_soldier_scope` from
  `backend/app/services/authority.py`; `UnifiedSoldierModal`'s `TABS`
  computation (`frontend/src/components/UnifiedSoldierModal.tsx:66-70`).
- Produces: nothing new — this task adds coverage only, per the "Investigation
  finding" in this plan's Architecture section. No production code changes.

**Why no backend task exists here:** the task brief for this batch requires
determining, by reading the actual authorization chain, whether item 16 is a
frontend-only gate bug or also needs a backend fix. Backend investigation
(`backend/app/routes/soldiers.py:583`, `backend/app/services/authority.py:355-385`)
found the commander-in-scope override already implemented and already covered
by both a unit test (`test_commander_sees_own_subtree_always`,
`backend/app/services/tests/test_authority.py:288`) and an HTTP-level
integration test using the *default, restrictive* transparency setting
(`test_duty_history_200_for_plain_soldier_commanding_target_node`,
`backend/tests/integration/test_soldiers_api.py:272`) — this is exactly the
"commander in scope, soldier's visibility otherwise restricted" scenario item
16 describes, and it already asserts `200`. No backend edit is made in this
task; adding a duplicate test would not increase coverage.

- [ ] **Step 1: Write the frontend regression test**

Add a new `describe` block to `frontend/src/components/UnifiedSoldierModal.test.tsx`
(the file already has a `renderModal()` helper, a `soldier` fixture, and
mocks `../auth/AuthContext`'s `useAuth` via `mockUseAuth` — reuse all of
these; it does not currently mock `../api/constraints`'s
`listSoldierConstraints` differently per test, so the existing top-level mock
at line 14-18 is reused unchanged):

```tsx
describe("UnifiedSoldierModal duty-history tab visibility for a commander", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  test("a commander (not admin/DM) still sees the duty_history tab for a soldier outside their direct-report list", async () => {
    // Regression lock for item 16: the tab must render for any commander,
    // not just admins/duty-managers — this soldier is not the commander's
    // direct report, only somewhere in their commanded subtree, which is
    // exactly the scenario the backend's can_view_soldier_scope already
    // covers (see backend/app/services/tests/test_authority.py and
    // backend/tests/integration/test_soldiers_api.py). The frontend TABS
    // list must not additionally gate this.
    mockUseAuth.mockReturnValue({
      user: { personal_number: "cmdr-scope-1", role: "soldier", is_duty_manager: false, is_commander: true },
    });
    renderModal({ personal_number: "9999999" });

    expect(await screen.findByTestId("modal-tab-duty_history")).toBeInTheDocument();
  });
});
```

This asserts against `data-testid="modal-tab-duty_history"` — confirm this
testid convention matches the file's existing tab buttons (the file already
uses `screen.getByTestId("modal-tab-profile")` at multiple call sites, e.g.
line 94, so `modal-tab-duty_history` follows the same `modal-tab-${tab}`
pattern used for every entry in `ALL_TABS`).

- [ ] **Step 2: Run the test**

Run: `cd frontend && npm test -- UnifiedSoldierModal.test.tsx`
Expected: PASS immediately — no production code change is needed, because
`TABS` (line 66-70) already includes `"duty_history"` in every branch
(`canViewAll`, `isSelf`, and the fallback for a plain non-commander/DM/admin
viewer). This is intentional: the test exists to catch a future regression if
someone later adds a conditional around the `duty_history` entry in `TABS`
without checking command scope, not to fix a currently-broken assertion.

- [ ] **Step 3: Run full frontend verification**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.test.tsx
git commit -m "test: lock duty-history tab visibility for in-scope commanders (item 16 regression coverage)"
```

---

## Verification

Run the full backend and frontend suites before considering this batch done:

```bash
# Backend (from backend/, venv activated)
pytest -q
pytest -m "duty or scoring" -q
pytest -m soldiers -q

# Frontend (from frontend/)
npm test
npm run lint
npm run typecheck
```

"Done" for this batch means:

- `CommandDashboardPage.tsx` no longer imports or renders `HierarchyTree`; its
  "soldiers" panel shows a read-only per-node count summary and a working link
  to `/team`; `/team` (`TeamHierarchyPage.tsx`) is unchanged and remains the
  sole place with full hierarchy/soldier management from the dashboard flow.
  No dead `activePanel` state remains.
- The commander dashboard's `upcoming` endpoint and `summary_cards`'s
  `upcoming_duties_7d` count both include `algorithm_draft` assignments, each
  assignment in the `upcoming` response carries a `status` field, and
  `UpcomingSnapshot.tsx` visually distinguishes drafts with the existing
  "טיוטה" badge pattern.
- A soldier's own `HomePage` upcoming-duties widget
  (`UpcomingDutiesWidget.tsx`, fed via `GET /assignments/effective
  ?include_drafts=true`) shows their own `algorithm_draft` assignments with
  the same draft badge; every other consumer of `GET /assignments/effective`
  is unchanged (still published-only by default).
  `scoring.effective_duty_spans` (the scoring/effort/fairness source of
  truth) is behaviorally unchanged and regression-tested to prove it still
  never returns `algorithm_draft` spans.
- A regression test locks in that the duty-history tab is visible to
  commanders regardless of a soldier's own out-of-direct-scope status,
  matching the already-correct backend `can_view_soldier_scope` behavior — no
  backend changes were needed for item 16 (documented finding above).
