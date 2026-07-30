# Marketplace Filter UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the marketplace page's unit ("יחידה") filter — currently a flat `<select multiple>` that silently drops sub-units — with a hierarchical tree-combobox, and replace the duty-type filter with a dropdown-with-checkboxes, matching patterns that already exist elsewhere in the codebase.

**Architecture:** A shared `PopoverDropdown` shell (trigger button + outside-click-to-close popover chrome) is extracted first, since both new filter components need identical popover behavior — building them independently would duplicate that logic twice. `CheckboxListDropdown` and `HierarchyTreeDropdown` are then built on top of it: the former wraps a flat checkbox list (replacing the checkbox-list body currently duplicated inside `DataTable.tsx`'s private `ColumnFilterDropdown`), the latter wraps the existing `HierarchyNodeFilter.tsx` recursive tree component (which already accepts `{nodes, selected, onChange}` as props — it does not self-fetch). Both get wired into `SwapsPage.tsx`'s marketplace/board filter row, replacing the two `<select multiple>` elements. No backend changes are needed — `GET /swaps/board` already expands a selected node to its full subtree server-side, and already accepts a flat list of `duty_type_id`s.

**Tech Stack:** React/TypeScript, Tailwind CSS, vitest, `@testing-library/react`.

## Global Constraints

- Hebrew UI strings only — reuse existing i18n keys (`swaps.filter_node`, `swaps.filter_duty_type`) where already present; add new ones to `frontend/src/i18n/he.json` only if needed for new UI chrome (e.g. "בחר הכל"/"נקה").
- Do not change `backend/app/routes/swaps.py`'s `GET /swaps/board` — it already handles subtree expansion and duty-type filtering correctly server-side.
- New components must be dark-mode aware (match existing `dark:` class usage throughout the codebase).
- `frontend/src/components/HierarchyNodeFilter.tsx`'s real props are `{ nodes: NodeDTO[]; selected: string[]; onChange: (ids: string[]) => void }` (confirmed by reading the file in full) — it does not self-fetch and has no `tree` prop; use `nodes`, not `tree`.

---

## File Structure

- **Create:** `frontend/src/components/PopoverDropdown.tsx` — shared trigger-button + outside-click-to-close popover shell, used by both dropdowns below.
- **Create:** `frontend/src/components/CheckboxListDropdown.tsx` — flat checkbox list with a "select all" row, built on `PopoverDropdown`.
- **Create:** `frontend/src/components/HierarchyTreeDropdown.tsx` — wraps `HierarchyNodeFilter` in a `PopoverDropdown`.
- **Modify:** `frontend/src/components/DataTable.tsx` — have `ColumnFilterDropdown` use `CheckboxListDropdown` internally (keeps existing table-column filter behavior identical, removes duplication).
- **Modify:** `frontend/src/pages/SwapsPage.tsx` — replace both `<select multiple>` filters (unit at lines 554-572, duty type at lines 537-553) with the two new components; fix the unit filter's tree-flattening bug as part of the swap.
- **Test:** `frontend/src/components/PopoverDropdown.test.tsx`, `frontend/src/components/HierarchyTreeDropdown.test.tsx`, `frontend/src/components/CheckboxListDropdown.test.tsx` (new).

---

### Task 1: Extract the shared `PopoverDropdown` shell

**Files:**
- Create: `frontend/src/components/PopoverDropdown.tsx`
- Test: `frontend/src/components/PopoverDropdown.test.tsx`

**Interfaces:**
- Produces: `<PopoverDropdown triggerLabel={string} badgeCount={number} panelClassName={string}>{(close: () => void) => ReactNode}</PopoverDropdown>` — renders a trigger button (with an optional count badge) and, when open, an absolutely-positioned panel below it that closes on outside click. The panel content is a render-prop so callers can close the popover themselves (e.g. after a selection, if desired) without lifting `open` state out.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/PopoverDropdown.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PopoverDropdown from "./PopoverDropdown";

describe("PopoverDropdown", () => {
  it("is closed by default and opens the panel on trigger click", () => {
    render(
      <PopoverDropdown triggerLabel="סנן" badgeCount={0}>
        {() => <div>תוכן הפאנל</div>}
      </PopoverDropdown>
    );
    expect(screen.queryByText("תוכן הפאנל")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("תוכן הפאנל")).toBeInTheDocument();
  });

  it("shows a count badge when badgeCount > 0, and hides it at 0", () => {
    const { rerender } = render(
      <PopoverDropdown triggerLabel="סנן" badgeCount={2}>{() => <div />}</PopoverDropdown>
    );
    expect(screen.getByText("2")).toBeInTheDocument();
    rerender(<PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div />}</PopoverDropdown>);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("closes when clicking outside the popover", () => {
    render(
      <div>
        <PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div>תוכן הפאנל</div>}</PopoverDropdown>
        <div data-testid="outside">מחוץ</div>
      </div>
    );
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("תוכן הפאנל")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByText("תוכן הפאנל")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/PopoverDropdown.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/components/PopoverDropdown.tsx
import { useState, useRef, useEffect, type ReactNode } from "react";

interface Props {
  triggerLabel: string;
  badgeCount: number;
  panelClassName?: string;
  children: (close: () => void) => ReactNode;
}

export default function PopoverDropdown({ triggerLabel, badgeCount, panelClassName, children }: Props) {
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
        {badgeCount > 0 && (
          <span className="bg-blue-600 text-white rounded-full text-[10px] px-1.5">{badgeCount}</span>
        )}
        <span>▾</span>
      </button>
      {open && (
        <div
          className={
            panelClassName ??
            "absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-40 max-h-56 flex flex-col"
          }
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/PopoverDropdown.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PopoverDropdown.tsx frontend/src/components/PopoverDropdown.test.tsx
git commit -m "feat: add shared PopoverDropdown shell for filter dropdowns"
```

---

### Task 2: Build `CheckboxListDropdown` on `PopoverDropdown`, refactor `DataTable`'s column filter to use it

**Files:**
- Create: `frontend/src/components/CheckboxListDropdown.tsx`
- Modify: `frontend/src/components/DataTable.tsx:60-168` (`ColumnFilterDropdown` — refactor to use the new component internally)
- Test: `frontend/src/components/CheckboxListDropdown.test.tsx`

**Interfaces:**
- Consumes: `PopoverDropdown` from Task 1.
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

- [ ] **Step 3: Implement the component on top of `PopoverDropdown`**

```tsx
// frontend/src/components/CheckboxListDropdown.tsx
import PopoverDropdown from "./PopoverDropdown";

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
  const allSelected = items.length > 0 && items.every((i) => selected.includes(i.id));

  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  }

  function toggleAll() {
    onChange(allSelected ? [] : items.map((i) => i.id));
  }

  return (
    <PopoverDropdown triggerLabel={triggerLabel} badgeCount={selected.length}>
      {() => (
        <>
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
        </>
      )}
    </PopoverDropdown>
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

- [ ] **Step 7: Run frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no new errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/CheckboxListDropdown.tsx frontend/src/components/CheckboxListDropdown.test.tsx frontend/src/components/DataTable.tsx
git commit -m "refactor: extract CheckboxListDropdown on the shared PopoverDropdown shell"
```

---

### Task 3: Build `HierarchyTreeDropdown` on `PopoverDropdown` + the real `HierarchyNodeFilter`

**Files:**
- Create: `frontend/src/components/HierarchyTreeDropdown.tsx`
- Test: `frontend/src/components/HierarchyTreeDropdown.test.tsx`

**Interfaces:**
- Consumes: `PopoverDropdown` from Task 1; `HierarchyNodeFilter` from `frontend/src/components/HierarchyNodeFilter.tsx`, whose real props are `{ nodes: NodeDTO[]; selected: string[]; onChange: (ids: string[]) => void }` — it does not self-fetch. Its per-node expand/collapse toggle button has `aria-label="הרחב"` when collapsed and `aria-label="כווץ"` when expanded (rendered for every node, though the glyph is blank for leaf nodes); its checkbox has no explicit `aria-label` — its accessible name comes from the wrapping `<label>`'s text content, which is the node's name.
- Produces: `<HierarchyTreeDropdown nodes={NodeDTO[]} selected={string[]} onChange={(ids: string[]) => void} triggerLabel={string} />`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/HierarchyTreeDropdown.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import HierarchyTreeDropdown from "./HierarchyTreeDropdown";

const nodes = [
  { id: "a", name: "פיקוד צפון", parent_id: null, path_ids: ["a"], children: [
    { id: "a1", name: "גדוד 1", parent_id: "a", path_ids: ["a", "a1"], children: [] },
  ] },
];

describe("HierarchyTreeDropdown", () => {
  it("shows top-level nodes expanded by default (matching HierarchyNodeFilter's own default), toggling collapse hides children", () => {
    render(<HierarchyTreeDropdown nodes={nodes} selected={[]} onChange={() => {}} triggerLabel="יחידה" />);
    fireEvent.click(screen.getByText("יחידה"));
    expect(screen.getByText("פיקוד צפון")).toBeInTheDocument();
    // HierarchyNodeFilter's per-node expand state defaults to expanded=true, so the
    // child is visible immediately — this differs from a naive "collapsed by default"
    // tree, but matches the real component's actual behavior.
    expect(screen.getByText("גדוד 1")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("כווץ"));
    expect(screen.queryByText("גדוד 1")).not.toBeInTheDocument();
  });

  it("checking a node calls onChange with that node's id", () => {
    let selected: string[] = [];
    render(<HierarchyTreeDropdown nodes={nodes} selected={[]} onChange={(ids) => { selected = ids; }} triggerLabel="יחידה" />);
    fireEvent.click(screen.getByText("יחידה"));
    fireEvent.click(screen.getByLabelText("פיקוד צפון"));
    expect(selected).toEqual(["a"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HierarchyTreeDropdown.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/components/HierarchyTreeDropdown.tsx
import PopoverDropdown from "./PopoverDropdown";
import HierarchyNodeFilter from "./HierarchyNodeFilter";
import type { NodeDTO } from "../api/hierarchy";

interface Props {
  nodes: NodeDTO[];
  selected: string[];
  onChange: (ids: string[]) => void;
  triggerLabel: string;
}

export default function HierarchyTreeDropdown({ nodes, selected, onChange, triggerLabel }: Props) {
  return (
    <PopoverDropdown
      triggerLabel={triggerLabel}
      badgeCount={selected.length}
      panelClassName="absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-56 max-h-72 overflow-y-auto p-2"
    >
      {() => <HierarchyNodeFilter nodes={nodes} selected={selected} onChange={onChange} />}
    </PopoverDropdown>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/HierarchyTreeDropdown.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HierarchyTreeDropdown.tsx frontend/src/components/HierarchyTreeDropdown.test.tsx
git commit -m "feat: add HierarchyTreeDropdown wrapping HierarchyNodeFilter in a popover"
```

---

### Task 4: Wire both new dropdowns into the marketplace filter bar

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:28-31, 178-182, 537-572`
- Test: manual (page-level integration; component-level behavior already covered by Tasks 1-3's unit tests)

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
      nodes={hierarchyNodes}
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
- The unit filter now opens a tree popover, expandable/collapsible per node, and selecting a top-level command still correctly filters the board to include all its sub-units (server-side subtree expansion already works — confirm end-to-end).
- The duty-type filter now opens a checkbox-list popover with a working "select all."
- Both show a badge count when filters are active, and clearing them restores the full board.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx
git commit -m "feat: replace flat marketplace filters with hierarchical tree and checkbox-list dropdowns"
```

---

## Self-Review Notes

- Both spec items (unit hierarchy filter, duty-type checkbox filter) are covered by Tasks 1-4.
- No backend changes needed, confirmed by investigation — `GET /swaps/board`'s subtree expansion already handles the corrected unit-filter selection semantics correctly.
- Task 4 also fixes the pre-existing "only top-level nodes shown, children silently dropped" bug as a side effect of properly consuming the nested tree, called out explicitly rather than left implicit.
- A pre-flight review of this plan alongside the others in this batch flagged that `CheckboxListDropdown` and `HierarchyTreeDropdown` would otherwise duplicate identical popover/outside-click boilerplate — Task 1 extracts that shell first specifically to avoid shipping the duplication this plan's own stated goal is to reduce.
- `HierarchyNodeFilter`'s real prop names (`nodes`, not `tree`) and its actual expand/collapse `aria-label`s (`"הרחב"`/`"כווץ"`) and checkbox accessible-name behavior (via wrapping `<label>` text, not a dedicated `aria-label`) were confirmed by reading the file in full — Task 3's test uses these real values instead of a guessed selector.
- No placeholders remain.
