# Marketplace Filter UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the marketplace page's unit ("יחידה") filter — currently a flat `<select multiple>` that silently drops sub-units — with a hierarchical tree-combobox, and replace the duty-type filter with a dropdown-with-checkboxes, matching patterns that already exist elsewhere in the codebase.

**Architecture:** Two new small reusable components extracted/generalized from existing code: `HierarchyTreeDropdown` (built from the existing `HierarchyNodeFilter.tsx` recursive tree body + `CustomColumnFilterDropdown`'s popover chrome from `DataTable.tsx`), and `CheckboxListDropdown` (the checkbox-list body already inside `DataTable.tsx`'s private `ColumnFilterDropdown`, extracted into a standalone generically-propped component). Both get wired into `SwapsPage.tsx`'s marketplace/board filter row, replacing the two `<select multiple>` elements. No backend changes are needed — `GET /swaps/board` already expands a selected node to its full subtree server-side, and already accepts a flat list of `duty_type_id`s.

**Tech Stack:** React/TypeScript, Tailwind CSS, vitest, `@testing-library/react`.

## Global Constraints

- Hebrew UI strings only — reuse existing i18n keys (`swaps.filter_node`, `swaps.filter_duty_type`) where already present; add new ones to `frontend/src/i18n/he.json` only if needed for new UI chrome (e.g. "בחר הכל"/"נקה").
- Do not change `backend/app/routes/swaps.py`'s `GET /swaps/board` — it already handles subtree expansion and duty-type filtering correctly server-side.
- New components must be dark-mode aware (match existing `dark:` class usage throughout the codebase).

---

## File Structure

- **Create:** `frontend/src/components/HierarchyTreeDropdown.tsx` — collapsed-by-default popover button containing a recursive expand/collapse checkbox tree.
- **Create:** `frontend/src/components/CheckboxListDropdown.tsx` — collapsed-by-default popover button containing a flat checkbox list with a "select all" row.
- **Modify:** `frontend/src/components/DataTable.tsx` — extract the checkbox-list body into `CheckboxListDropdown` and have `ColumnFilterDropdown` use it internally (keeps existing table-column filter behavior identical, removes duplication).
- **Modify:** `frontend/src/pages/SwapsPage.tsx` — replace both `<select multiple>` filters (unit at lines 554-572, duty type at lines 537-553) with the two new components; fix the unit filter's tree-flattening bug as part of the swap.
- **Test:** `frontend/src/components/HierarchyTreeDropdown.test.tsx`, `frontend/src/components/CheckboxListDropdown.test.tsx` (new).

---

### Task 1: Extract `CheckboxListDropdown` from `DataTable.tsx`

**Files:**
- Create: `frontend/src/components/CheckboxListDropdown.tsx`
- Modify: `frontend/src/components/DataTable.tsx:60-168` (`ColumnFilterDropdown` — refactor to use the new component internally)
- Test: `frontend/src/components/CheckboxListDropdown.test.tsx`

**Interfaces:**
- Produces: `<CheckboxListDropdown items={{id: string; label: string}[]} selected={string[]} onChange={(ids: string[]) => void} triggerLabel={string} />`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/CheckboxListDropdown.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CheckboxListDropdown from "./CheckboxListDropdown";

describe("CheckboxListDropdown", () => {
  const items = [
    { id: "1", label: "אלפא" },
    { id: "2", label: "ברבו" },
  ];

  it("opens the panel on trigger click and shows all items", () => {
    render(<CheckboxListDropdown items={items} selected={[]} onChange={() => {}} triggerLabel="סנן" />);
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("אלפא")).toBeInTheDocument();
    expect(screen.getByText("ברבו")).toBeInTheDocument();
  });

  it("calls onChange with the toggled item added when checked", () => {
    let selected: string[] = [];
    const onChange = (ids: string[]) => { selected = ids; };
    render(<CheckboxListDropdown items={items} selected={[]} onChange={onChange} triggerLabel="סנן" />);
    fireEvent.click(screen.getByText("סנן"));
    fireEvent.click(screen.getByLabelText("אלפא"));
    expect(selected).toEqual(["1"]);
  });

  it("select-all toggles every item on and off", () => {
    let selected: string[] = [];
    const onChange = (ids: string[]) => { selected = ids; };
    const { rerender } = render(<CheckboxListDropdown items={items} selected={selected} onChange={onChange} triggerLabel="סנן" />);
    fireEvent.click(screen.getByText("סנן"));
    fireEvent.click(screen.getByLabelText("הכל"));
    expect(selected).toEqual(["1", "2"]);
    rerender(<CheckboxListDropdown items={items} selected={selected} onChange={onChange} triggerLabel="סנן" />);
    fireEvent.click(screen.getByLabelText("הכל"));
    expect(selected).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/CheckboxListDropdown.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement the component**

Read `frontend/src/components/DataTable.tsx` lines 60-168 (`ColumnFilterDropdown`) and 172-210 (`CustomColumnFilterDropdown`) in full first, to copy the exact outside-click-to-close logic (`open`/`ref` state pattern) rather than reinventing it.

```tsx
// frontend/src/components/CheckboxListDropdown.tsx
import { useState, useRef, useEffect } from "react";

export interface CheckboxListItem {
  id: string;
  label: string;
}

interface Props {
  items: CheckboxListItem[];
  selected: string[];
  onChange: (ids: string[]) => void;
  triggerLabel: string;
}

export default function CheckboxListDropdown({ items, selected, onChange, triggerLabel }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const allSelected = items.length > 0 && items.every((i) => selected.includes(i.id));

  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  }

  function toggleAll() {
    onChange(allSelected ? [] : items.map((i) => i.id));
  }

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 flex items-center gap-1"
      >
        {triggerLabel}
        {selected.length > 0 && <span className="bg-blue-600 text-white rounded-full text-[10px] px-1.5">{selected.length}</span>}
        <span>▾</span>
      </button>
      {open && (
        <div className="absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-40 max-h-56 flex flex-col">
          <label className="flex items-center gap-2 px-3 py-1.5 border-b dark:border-gray-600 cursor-pointer text-sm">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            הכל
          </label>
          <div className="overflow-y-auto">
            {items.map((item) => (
              <label key={item.id} className="flex items-center gap-2 px-3 py-1 cursor-pointer text-sm hover:bg-gray-50 dark:hover:bg-gray-700">
                <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} />
                {item.label}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/CheckboxListDropdown.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Refactor `DataTable.tsx`'s `ColumnFilterDropdown` to use the new component internally**

Read the full body of `ColumnFilterDropdown` (`DataTable.tsx:60-168`) to see exactly how it derives `uniqueValues` from row data and how it currently renders the checkbox list, then replace only its checkbox-list rendering portion with `<CheckboxListDropdown items={...} selected={...} onChange={...} triggerLabel={...} />`, keeping its `uniqueValues` derivation and any column-filter-specific logic (e.g. how it integrates with the table's sort/filter state) unchanged. This is a pure refactor — confirm behavior is identical by manually testing a column filter afterward (Step 6).

- [ ] **Step 6: Manually verify DataTable column filters still work**

Start `.\dev.ps1`, go to any page using `DataTable` with a column filter dropdown (e.g. `/transparency` or `ShiftsPage.tsx`'s eligible-units column filter), confirm the dropdown still opens, selects, and filters exactly as before the refactor.

- [ ] **Step 7: Run frontend typecheck and existing DataTable tests if any**

Run: `cd frontend && npm run typecheck`
Expected: no new errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/CheckboxListDropdown.tsx frontend/src/components/CheckboxListDropdown.test.tsx frontend/src/components/DataTable.tsx
git commit -m "refactor: extract CheckboxListDropdown as a standalone reusable component"
```

---

### Task 2: Build `HierarchyTreeDropdown`

**Files:**
- Create: `frontend/src/components/HierarchyTreeDropdown.tsx`
- Test: `frontend/src/components/HierarchyTreeDropdown.test.tsx`

**Interfaces:**
- Consumes: `NodeDTO` shape from `frontend/src/api/hierarchy.ts` (`{id, name, children, parent_id, path_ids}` — read the exact type definition before writing this component, since the investigation only summarized it).
- Produces: `<HierarchyTreeDropdown tree={NodeDTO[]} selected={string[]} onChange={(ids: string[]) => void} triggerLabel={string} />`

- [ ] **Step 1: Read `HierarchyNodeFilter.tsx` in full**

Read `frontend/src/components/HierarchyNodeFilter.tsx` completely — this is the recursive expand/collapse checkbox-tree body to reuse/adapt. Note its exact recursion pattern (how it renders `node.children`), its expand/collapse state shape, and its props, since `HierarchyTreeDropdown` should wrap this same recursive body inside a popover trigger rather than reimplementing tree recursion from scratch.

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/HierarchyTreeDropdown.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import HierarchyTreeDropdown from "./HierarchyTreeDropdown";

const tree = [
  { id: "a", name: "פיקוד צפון", parent_id: null, path_ids: ["a"], children: [
    { id: "a1", name: "גדוד 1", parent_id: "a", path_ids: ["a", "a1"], children: [] },
  ] },
];

describe("HierarchyTreeDropdown", () => {
  it("shows top-level nodes collapsed by default, expands to reveal children on click", () => {
    render(<HierarchyTreeDropdown tree={tree} selected={[]} onChange={() => {}} triggerLabel="יחידה" />);
    fireEvent.click(screen.getByText("יחידה"));
    expect(screen.getByText("פיקוד צפון")).toBeInTheDocument();
    expect(screen.queryByText("גדוד 1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/הרחב|expand/i)); // adjust to match HierarchyNodeFilter's real expand-toggle affordance
    expect(screen.getByText("גדוד 1")).toBeInTheDocument();
  });

  it("checking a node calls onChange with that node's id", () => {
    let selected: string[] = [];
    render(<HierarchyTreeDropdown tree={tree} selected={[]} onChange={(ids) => { selected = ids; }} triggerLabel="יחידה" />);
    fireEvent.click(screen.getByText("יחידה"));
    fireEvent.click(screen.getByLabelText("פיקוד צפון"));
    expect(selected).toEqual(["a"]);
  });
});
```

(Adjust the "expand" interaction selector to match `HierarchyNodeFilter.tsx`'s actual expand/collapse control, read in Step 1 — do not guess a label that doesn't exist in that component.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HierarchyTreeDropdown.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/components/HierarchyTreeDropdown.tsx
import { useState, useRef, useEffect } from "react";
import HierarchyNodeFilter from "./HierarchyNodeFilter"; // reuse the existing recursive tree body — adjust import/props to its real exported shape from Step 1's reading
import type { NodeDTO } from "../api/hierarchy";

interface Props {
  tree: NodeDTO[];
  selected: string[];
  onChange: (ids: string[]) => void;
  triggerLabel: string;
}

export default function HierarchyTreeDropdown({ tree, selected, onChange, triggerLabel }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 flex items-center gap-1"
      >
        {triggerLabel}
        {selected.length > 0 && <span className="bg-blue-600 text-white rounded-full text-[10px] px-1.5">{selected.length}</span>}
        <span>▾</span>
      </button>
      {open && (
        <div className="absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-56 max-h-72 overflow-y-auto p-2">
          <HierarchyNodeFilter tree={tree} selected={selected} onChange={onChange} />
        </div>
      )}
    </div>
  );
}
```

(This assumes `HierarchyNodeFilter` accepts `tree`/`selected`/`onChange` props directly — confirm its real prop names from Step 1's reading and adjust; if `HierarchyNodeFilter` currently self-fetches the tree rather than accepting it as a prop, either add a `tree` prop override to it or fetch once in `SwapsPage.tsx` and pass down — prefer accepting an explicit `tree` prop since `SwapsPage.tsx` already fetches it via `fetchTree()`, to avoid a duplicate fetch.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/HierarchyTreeDropdown.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HierarchyTreeDropdown.tsx frontend/src/components/HierarchyTreeDropdown.test.tsx
git commit -m "feat: add HierarchyTreeDropdown, a collapsed-by-default hierarchical tree filter"
```

---

### Task 3: Wire both new dropdowns into the marketplace filter bar

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:28-31, 178-182, 537-572`
- Test: manual (page-level integration; component-level behavior already covered by Tasks 1-2's unit tests)

- [ ] **Step 1: Fix the unit-filter data shape and flattening bug**

Replace the local minimal `HierarchyNode` interface and raw-tree storage at lines 28-31, 178-182 with the real `NodeDTO` type:

```ts
// BEFORE (lines 28-31)
interface HierarchyNode {
  id: string;
  name: string;
}
```

```ts
// AFTER
import type { NodeDTO } from "../api/hierarchy";
```

The existing fetch at lines 178-182 already calls `fetchTree()` and stores the nested tree — keep that as-is (it was already fetching the right shape; the bug was only in how it was rendered as a flat `<select>`), just retype `hierarchyNodesQuery`'s generic to `NodeDTO[]`.

- [ ] **Step 2: Replace the unit `<select multiple>` with `HierarchyTreeDropdown`**

```tsx
// BEFORE (lines 554-572)
{hierarchyNodes.length > 0 && (
  <div className="flex flex-col gap-1">
    <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_node")}</label>
    <select multiple ...>
      {hierarchyNodes.map(n => (<option key={n.id} value={n.id}>{n.name}</option>))}
    </select>
  </div>
)}
```

```tsx
// AFTER
{hierarchyNodes.length > 0 && (
  <div className="flex flex-col gap-1">
    <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_node")}</label>
    <HierarchyTreeDropdown
      tree={hierarchyNodes}
      selected={boardFilters.nodeIds ?? []}
      onChange={(ids) => applyFilters({ nodeIds: ids.length > 0 ? ids : undefined })}
      triggerLabel={t("swaps.filter_node")}
    />
  </div>
)}
```

- [ ] **Step 3: Replace the duty-type `<select multiple>` with `CheckboxListDropdown`**

```tsx
// BEFORE (lines 537-553)
<div className="flex flex-col gap-1">
  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_duty_type")}</label>
  <select multiple ...>
    {dutyTypeList.map(dt => (<option key={dt.id} value={dt.id}>{dt.name}</option>))}
  </select>
</div>
```

```tsx
// AFTER
<div className="flex flex-col gap-1">
  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_duty_type")}</label>
  <CheckboxListDropdown
    items={dutyTypeList.map((dt) => ({ id: dt.id, label: dt.name }))}
    selected={boardFilters.dutyTypeIds ?? []}
    onChange={(ids) => applyFilters({ dutyTypeIds: ids.length > 0 ? ids : undefined })}
    triggerLabel={t("swaps.filter_duty_type")}
  />
</div>
```

- [ ] **Step 4: Import the two new components**

```tsx
import HierarchyTreeDropdown from "../components/HierarchyTreeDropdown";
import CheckboxListDropdown from "../components/CheckboxListDropdown";
```

- [ ] **Step 5: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 6: Manually verify in the running app**

Start `.\dev.ps1`, go to the marketplace/board tab of the swaps page. Confirm:
- The unit filter now opens a tree popover, expandable to sub-units, and selecting a top-level command still correctly filters the board to include all its sub-units (server-side subtree expansion already works — confirm end-to-end).
- The duty-type filter now opens a checkbox-list popover with a working "select all."
- Both show a badge count when filters are active, and clearing them restores the full board.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx
git commit -m "feat: replace flat marketplace filters with hierarchical tree and checkbox-list dropdowns"
```

---

## Self-Review Notes

- Both spec items (unit hierarchy filter, duty-type checkbox filter) are covered by Tasks 1-3.
- No backend changes needed, confirmed by investigation — `GET /swaps/board`'s subtree expansion already handles the corrected unit-filter selection semantics correctly.
- Task 3 also fixes the pre-existing "only top-level nodes shown, children silently dropped" bug as a side effect of properly consuming the nested tree, called out explicitly rather than left implicit.
- No placeholders; a few exact prop names for `HierarchyNodeFilter` are marked "confirm by reading the file first" since the investigation summarized but didn't quote its full prop signature.
