# Auto-Assign Scope Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a manager quickly pre-select shift rows on `ShiftsPage.tsx` by duty type or by a computed "eligibility group" (reusing the same connected-components computation already powering the transparency fairness view), before running the existing manual "שבץ אוטומטי" flow.

**Architecture:** A thin new backend endpoint (`GET /scoring/eligibility-groups`) wraps the existing `fairness_components()` service function, stripping the per-soldier detail it doesn't need. The frontend adds two quick-filter controls above the shifts table that union matching row IDs into the existing `selectedShiftIds` state — no change to the job-creation flow itself.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Vitest + Testing Library (frontend), `@tanstack/react-query` for data fetching.

## Global Constraints

- No changes to `CreateJobRequest`/the algorithm job-creation flow — filters only affect table-row selection.
- Hebrew UI strings go through `t("...")` / `frontend/src/i18n/he.json`.
- `pytest -q` (backend) and `npm test` (frontend) must stay green after every task.

---

### Task 1: Include `duty_type_ids` in `fairness_components()` output

**Files:**
- Modify: `backend/app/services/scoring.py:668-742` (`_build_fairness_components`)
- Test: `backend/app/services/tests/test_scoring.py` (or wherever `fairness_components`/`_build_fairness_components` is tested — search first)

**Interfaces:**
- Produces: each component dict gains `"duty_type_ids": list[str]` (sorted UUID strings) alongside the existing `"duty_type_names"` — consumed by Task 2's new endpoint.

- [ ] **Step 1: Write the failing test**

Find the existing test(s) for `fairness_components`/`_build_fairness_components` (search `backend/app/services/tests/` for `fairness_components`). Add:

```python
def test_fairness_components_includes_duty_type_ids(app_session, soldier_factory, duty_type_factory):
    dt = duty_type_factory(name="שמירה")
    soldier = soldier_factory()
    # set up soldier eligibility for dt via whatever this test file's existing
    # fairness_components tests already use to establish eligibility (exemptions,
    # node scope, etc. — copy that setup rather than re-deriving it)
    result = svc.fairness_components(app_session)
    component = next(c for c in result["components"] if "שמירה" in c["duty_type_names"])
    assert component["duty_type_ids"] == [str(dt.id)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_scoring.py -k "duty_type_ids" -v`
Expected: FAIL — `KeyError: 'duty_type_ids'`.

- [ ] **Step 3: Add the field**

In `backend/app/services/scoring.py`, inside `_build_fairness_components`, update the component-building loop (around line 721-731):

```python
    components = []
    for g in groups.values():
        effs = [effort_by_id.get(sid, 0.0) for sid in g["soldiers"]]
        comp_type_ids: set[uuid.UUID] = g["type_ids"]
        components.append({
            "duty_type_ids": sorted(str(tid) for tid in comp_type_ids),
            "duty_type_names": sorted(type_names[tid] for tid in comp_type_ids if tid in type_names),
            "soldier_count": len(g["soldiers"]),
            "effort": _effort_stats(effs),
            "soldiers": sorted((soldier_obj(s, comp_type_ids) for s in g["soldiers"]),
                               key=lambda o: o["effort_score"], reverse=True),
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_scoring.py -k "duty_type_ids" -v`
Expected: PASS

- [ ] **Step 5: Run the full scoring test suite to check for regressions**

Run: `pytest backend/app/services/tests/test_scoring.py backend/app/routes/tests/test_scoring_routes.py -v` (adjust the routes test filename if different — search first)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scoring.py backend/app/services/tests/test_scoring.py
git commit -m "feat: include duty_type_ids in fairness_components output"
```

---

### Task 2: `GET /scoring/eligibility-groups` summary endpoint

**Files:**
- Modify: `backend/app/routes/scoring.py:137-144` (add new route near `fairness_components`)
- Test: `backend/app/routes/tests/test_scoring_routes.py` (search for the actual filename first)

**Interfaces:**
- Consumes: `svc.fairness_components(session)` (existing, now including `duty_type_ids` per Task 1).
- Produces: `GET /scoring/eligibility-groups` → `list[{"duty_type_ids": list[str], "duty_type_names": list[str], "soldier_count": int}]` — consumed by Task 3's frontend wrapper.

- [ ] **Step 1: Write the failing test**

```python
def test_eligibility_groups_returns_summary_without_soldier_list(client, admin_session, soldier_factory, duty_type_factory):
    dt = duty_type_factory(name="שמירה")
    # establish at least one eligible soldier for dt, same setup pattern as
    # the existing fairness-components route test in this file
    resp = client.get("/scoring/eligibility-groups", headers=admin_session)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    group = next(g for g in body if "שמירה" in g["duty_type_names"])
    assert "duty_type_ids" in group
    assert "soldier_count" in group
    assert "soldiers" not in group
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/routes/tests/test_scoring_routes.py -k "eligibility_groups" -v`
Expected: FAIL — 404 (route doesn't exist).

- [ ] **Step 3: Add the route**

In `backend/app/routes/scoring.py`, add right after the existing `fairness_components` route (line 137-144):

```python
@router.get("/eligibility-groups")
def eligibility_groups(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[dict]:
    """Lightweight view of fairness_components() for scoping auto-assign selection —
    same connected components, without the per-soldier detail."""
    full = svc.fairness_components(session)
    return [
        {
            "duty_type_ids": c["duty_type_ids"],
            "duty_type_names": c["duty_type_names"],
            "soldier_count": c["soldier_count"],
        }
        for c in full["components"]
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/routes/tests/test_scoring_routes.py -k "eligibility_groups" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/scoring.py backend/app/routes/tests/test_scoring_routes.py
git commit -m "feat: add GET /scoring/eligibility-groups summary endpoint"
```

---

### Task 3: Frontend API wrapper for eligibility groups

**Files:**
- Modify: `frontend/src/api/scoring.ts`
- Test: `frontend/src/api/scoring.test.ts` (create if it doesn't exist — check first)

**Interfaces:**
- Produces: `interface EligibilityGroup { duty_type_ids: string[]; duty_type_names: string[]; soldier_count: number }`, `listEligibilityGroups(): Promise<EligibilityGroup[]>` — consumed by Task 4.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import { listEligibilityGroups } from "./scoring";

vi.mock("./client");

describe("listEligibilityGroups", () => {
  it("calls GET /scoring/eligibility-groups", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [{ duty_type_ids: ["t1"], duty_type_names: ["שמירה"], soldier_count: 5 }] });
    const result = await listEligibilityGroups();
    expect(api.get).toHaveBeenCalledWith("/scoring/eligibility-groups");
    expect(result).toEqual([{ duty_type_ids: ["t1"], duty_type_names: ["שמירה"], soldier_count: 5 }]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- scoring.test` (from `frontend/`)
Expected: FAIL — `listEligibilityGroups is not a function`.

- [ ] **Step 3: Add the wrapper**

In `frontend/src/api/scoring.ts`, add after `getFairnessComponents` (line 86-88):

```ts
export interface EligibilityGroup {
  duty_type_ids: string[];
  duty_type_names: string[];
  soldier_count: number;
}

export async function listEligibilityGroups(): Promise<EligibilityGroup[]> {
  return (await api.get<EligibilityGroup[]>(`/scoring/eligibility-groups`)).data;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- scoring.test` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/scoring.ts frontend/src/api/scoring.test.ts
git commit -m "feat: add listEligibilityGroups frontend API wrapper"
```

---

### Task 4: Quick-filter controls on `ShiftsPage.tsx`

**Files:**
- Modify: `frontend/src/pages/ShiftsPage.tsx`
- Modify: `frontend/src/queryKeys.ts` (add an `eligibilityGroups()` key if the file follows a per-endpoint key pattern — check first)
- Modify: `frontend/src/i18n/he.json` (add `shifts.filter_by_duty_type`, `shifts.filter_by_eligibility_group`)
- Test: `frontend/src/pages/ShiftsPage.test.tsx`

**Interfaces:**
- Consumes: `listEligibilityGroups()` from Task 3, existing `dutyTypes` (from `listDutyTypes`, already loaded at `ShiftsPage.tsx:438`), existing `selectedShiftIds`/`setSelectedShiftIds` state (`ShiftsPage.tsx:419`), existing `displayedShifts` (`ShiftsPage.tsx:433-436`).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/ShiftsPage.test.tsx` (reuse the file's existing render helper, mock setup for `listShifts`/`listDutyTypes`, etc.):

```tsx
import * as scoringApi from "../api/scoring";
vi.mock("../api/scoring");

it("selecting a duty type in the quick filter checks all matching shift rows", async () => {
  vi.mocked(shiftsApi.listShifts).mockResolvedValue([
    makeShift({ id: "s1", duty_type_id: "dt1" }),
    makeShift({ id: "s2", duty_type_id: "dt2" }),
  ]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([
    { id: "dt1", name: "שמירה" }, { id: "dt2", name: "מטבח" },
  ] as never);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([]);
  renderShiftsPage();
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByTestId("quick-filter-duty-type"), ["dt1"]);
  expect(screen.getByTestId(`shift-row-checkbox-s1`)).toBeChecked();
  expect(screen.getByTestId(`shift-row-checkbox-s2`)).not.toBeChecked();
});

it("selecting an eligibility group checks all shift rows whose duty type is in the group", async () => {
  vi.mocked(shiftsApi.listShifts).mockResolvedValue([
    makeShift({ id: "s1", duty_type_id: "dt1" }),
    makeShift({ id: "s2", duty_type_id: "dt2" }),
  ]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([
    { id: "dt1", name: "שמירה" }, { id: "dt2", name: "מטבח" },
  ] as never);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([
    { duty_type_ids: ["dt1"], duty_type_names: ["שמירה"], soldier_count: 12 },
  ]);
  renderShiftsPage();
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByTestId("quick-filter-eligibility-group"), ["0"]);
  expect(screen.getByTestId(`shift-row-checkbox-s1`)).toBeChecked();
  expect(screen.getByTestId(`shift-row-checkbox-s2`)).not.toBeChecked();
});
```

Before finalizing, read the top of `ShiftsPage.test.tsx` to copy its actual `makeShift`/render helper/mock module names — the snippet above uses placeholder names (`makeShift`, `renderShiftsPage`, `shiftsApi`, `dutyConfigApi`) that must match what the file already defines. Also check whether the existing shift-row checkbox already carries a `data-testid` (search the file for `shift-row-checkbox` or similar around line 527-531 of `ShiftsPage.tsx`); if it doesn't, add one as part of Step 3 below so the test can target it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- ShiftsPage -t "quick filter"` (from `frontend/`)
Expected: FAIL — `getByTestId("quick-filter-duty-type")` not found.

- [ ] **Step 3: Add the two quick-filter controls**

In `frontend/src/pages/ShiftsPage.tsx`, add the import (near the other API imports, around line 15):

```tsx
import { listEligibilityGroups, EligibilityGroup } from "../api/scoring";
```

Add a query for the groups, alongside the existing `dutyTypesQuery` (around line 438-439):

```tsx
const eligibilityGroupsQuery = useQuery({ queryKey: queryKeys.eligibilityGroups(), queryFn: listEligibilityGroups });
const eligibilityGroups = useMemo(() => eligibilityGroupsQuery.data ?? [], [eligibilityGroupsQuery.data]);
```

If `frontend/src/queryKeys.ts` follows a simple per-endpoint factory pattern (check the file — it likely has something like `shifts: (...) => [...]`), add:

```ts
eligibilityGroups: () => ["eligibilityGroups"] as const,
```

Add two handler functions near the other `handle*` callbacks (after `handleDelete`, around line 514):

```tsx
const selectByDutyTypeIds = useCallback((dutyTypeIds: string[]) => {
  const matching = displayedShifts.filter(s => dutyTypeIds.includes(s.duty_type_id)).map(s => s.id);
  setSelectedShiftIds(prev => Array.from(new Set([...prev, ...matching])));
}, [displayedShifts]);
```

Add the two select controls in the filter row, right after the existing date-range filters and before the "בחר הכל" block (around line 755-756):

```tsx
<label className="flex items-center gap-2">
  {t("shifts.filter_by_duty_type")}
  <select
    multiple
    data-testid="quick-filter-duty-type"
    className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 min-w-32"
    onChange={(e) => selectByDutyTypeIds(Array.from(e.target.selectedOptions, o => o.value))}
  >
    {dutyTypes.map(dt => <option key={dt.id} value={dt.id}>{dt.name}</option>)}
  </select>
</label>
{eligibilityGroups.length > 0 && (
  <label className="flex items-center gap-2">
    {t("shifts.filter_by_eligibility_group")}
    <select
      multiple
      data-testid="quick-filter-eligibility-group"
      className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 min-w-32"
      onChange={(e) => {
        const indices = Array.from(e.target.selectedOptions, o => Number(o.value));
        const ids = indices.flatMap(i => eligibilityGroups[i]?.duty_type_ids ?? []);
        selectByDutyTypeIds(ids);
      }}
    >
      {eligibilityGroups.map((g: EligibilityGroup, i: number) => (
        <option key={i} value={i}>{`${g.soldier_count} חיילים כשירים ל${g.duty_type_names.join(", ")}`}</option>
      ))}
    </select>
  </label>
)}
```

If the shift-row checkbox (line ~527-531) doesn't already carry a `data-testid`, add one: `data-testid={`shift-row-checkbox-${s.id}`}`.

In `frontend/src/i18n/he.json`, add to the `shifts` block:

```json
"filter_by_duty_type": "סנן לפי סוג תורנות",
"filter_by_eligibility_group": "סנן לפי קבוצת כשירות",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- ShiftsPage -t "quick filter"` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Run the full ShiftsPage suite to check for regressions**

Run: `npm test -- ShiftsPage` (from `frontend/`)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ShiftsPage.tsx frontend/src/queryKeys.ts frontend/src/i18n/he.json frontend/src/pages/ShiftsPage.test.tsx
git commit -m "feat: add quick-filter selection by duty type and eligibility group to ShiftsPage"
```

---

## Final verification

- [ ] Run `pytest -q` from `backend/` (with venv activated) — full backend suite green.
- [ ] Run `npm test` from `frontend/` — full frontend suite green.
- [ ] Run `npm run lint` from `frontend/` — zero warnings.
- [ ] Run `npm run typecheck` from `frontend/` — no errors.
- [ ] Manually verify in the browser (via `.\dev.ps1`): on the shifts page, selecting a duty type in the quick filter checks the matching rows; selecting an eligibility group (labeled like "12 חיילים כשירים ל...", matching the phrasing on the transparency page) checks the rows for that group's duty types; "שבץ אוטומטי" still works unchanged on the resulting selection.
