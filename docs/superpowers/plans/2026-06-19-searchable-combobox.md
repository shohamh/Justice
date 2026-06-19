# Searchable Combobox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace native `<select>` elements backed by dynamic/long option lists with one shared, fuzzy-searchable `Combobox` component, consolidating three existing duplicate implementations.

**Architecture:** One new component, `frontend/src/components/Combobox.tsx`, generalizing `ShiftTemplateFormModal`'s existing private `Combobox` (Fuse.js fuzzy search, portal-rendered dropdown) with three additions: tree-depth indentation (`depth` field, absorbs `UnitCalendarPage`'s bespoke dropdown and all hierarchy-node selects), group headers (`group` field, absorbs the `<optgroup>` rank selects), and disabled items + a selectable placeholder row. Every other task swaps one file's native `<select>`(s) for this component, preserving existing state/handlers untouched.

**Tech Stack:** React, TypeScript, Fuse.js (already a dependency), Vitest + Testing Library.

**Deviation from spec:** `SwapsPage.tsx`'s two filter selects (`filter_duty_type`, `filter_node`) turned out to be `<select multiple>` — multi-select checkbox-list semantics, not a single-value picker. `Combobox` is single-value only; converting these would change behavior, not just appearance. They are left as native `<select multiple>` and are **not** part of this plan.

---

### Task 1: Shared `Combobox` component

**Files:**
- Create: `frontend/src/components/Combobox.tsx`
- Test: `frontend/src/components/Combobox.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/Combobox.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import Combobox, { type ComboboxItem } from "./Combobox";

const items: ComboboxItem[] = [
  { id: "1", name: "Alpha" },
  { id: "2", name: "Beta" },
  { id: "3", name: "Gamma" },
];

test("shows the selected item's name in the input", () => {
  render(<Combobox items={items} value="2" onChange={() => {}} />);
  expect(screen.getByRole("textbox")).toHaveValue("Beta");
});

test("opening the input lists all items", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("textbox"));
  expect(screen.getByText("Alpha")).toBeInTheDocument();
  expect(screen.getByText("Beta")).toBeInTheDocument();
  expect(screen.getByText("Gamma")).toBeInTheDocument();
});

test("typing filters the list via fuzzy search", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  const input = screen.getByRole("textbox");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "gam" } });
  expect(screen.getByText("Gamma")).toBeInTheDocument();
  expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
});

test("clicking an item calls onChange with its id and closes the list", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("textbox"));
  fireEvent.pointerDown(screen.getByText("Beta"));
  expect(onChange).toHaveBeenCalledWith("2");
});

test("disabled items are not selectable", () => {
  const onChange = vi.fn();
  const withDisabled: ComboboxItem[] = [...items, { id: "4", name: "Delta", disabled: true }];
  render(<Combobox items={withDisabled} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("textbox"));
  fireEvent.pointerDown(screen.getByText("Delta"));
  expect(onChange).not.toHaveBeenCalled();
});

test("placeholder renders as a selectable first row that clears the value", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="1" onChange={onChange} placeholder="— none —" />);
  fireEvent.focus(screen.getByRole("textbox"));
  fireEvent.pointerDown(screen.getByText("— none —"));
  expect(onChange).toHaveBeenCalledWith("");
});

test("depth indents an item and shows a tree marker", () => {
  const withDepth: ComboboxItem[] = [
    { id: "1", name: "Root" },
    { id: "2", name: "Child", depth: 1 },
  ];
  render(<Combobox items={withDepth} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("textbox"));
  const child = screen.getByText("Child").closest("button");
  expect(child?.textContent).toContain("└");
});

test("group renders a header row before the first item of each group", () => {
  const grouped: ComboboxItem[] = [
    { id: "1", name: "Private", group: "Enlisted" },
    { id: "2", name: "Sergeant", group: "Enlisted" },
    { id: "3", name: "Captain", group: "Officers" },
  ];
  render(<Combobox items={grouped} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("textbox"));
  expect(screen.getByText("Enlisted")).toBeInTheDocument();
  expect(screen.getByText("Officers")).toBeInTheDocument();
  expect(screen.getAllByText("Enlisted")).toHaveLength(1);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- --run Combobox` (from `frontend/`)
Expected: FAIL — `Cannot find module './Combobox'`

- [ ] **Step 3: Write the component**

```tsx
// frontend/src/components/Combobox.tsx
import Fuse from "fuse.js";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface ComboboxItem {
  id: string;
  name: string;
  /** Tree-indentation depth (0 = top level). Renders a leading "└" marker for depth > 0. */
  depth?: number;
  /** Group header text. A header row is rendered before the first item of each new group. */
  group?: string;
  disabled?: boolean;
}

interface ComboboxProps {
  label?: string;
  items: ComboboxItem[];
  value: string;
  onChange: (id: string) => void;
  /** When set, renders a selectable first row with this text that calls onChange(""). */
  placeholder?: string;
  testId?: string;
}

// Combobox with Fuse.js fuzzy search — dropdown rendered via portal so it
// escapes overflow-y-auto containers (modals, panels).
export default function Combobox({ label, items, value, onChange, placeholder, testId }: ComboboxProps) {
  const allItems: ComboboxItem[] = placeholder !== undefined
    ? [{ id: "", name: placeholder }, ...items]
    : items;

  const [query, setQuery] = useState(() => allItems.find(i => i.id === value)?.name ?? "");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const fuse = new Fuse(allItems, { keys: ["name"], threshold: 0.4 });
  const results = query.trim() === "" ? allItems : fuse.search(query).map(r => r.item);

  useLayoutEffect(() => {
    if (open && inputRef.current) setRect(inputRef.current.getBoundingClientRect());
  }, [open]);

  // Sync displayed text when external value changes (e.g. after a quick-add selects a new item)
  useEffect(() => {
    const match = allItems.find(i => i.id === value);
    if (match) setQuery(match.name);
  }, [value, allItems]);

  return (
    <div>
      {label && <span className="text-xs text-gray-500 dark:text-gray-400 block mb-0.5">{label}</span>}
      <input
        ref={inputRef}
        type="text"
        value={query}
        autoComplete="off"
        data-testid={testId}
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => { setOpen(true); if (inputRef.current) setRect(inputRef.current.getBoundingClientRect()); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      />
      {open && results.length > 0 && rect && createPortal(
        <ul
          style={{ position: "fixed", top: rect.bottom + 2, left: rect.left, width: rect.width, zIndex: 9999 }}
          className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto"
        >
          {results.map((item, idx) => {
            const showGroup = item.group !== undefined && (idx === 0 || results[idx - 1].group !== item.group);
            const depth = item.depth ?? 0;
            return (
              <li key={item.id}>
                {showGroup && (
                  <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase">
                    {item.group}
                  </div>
                )}
                <button
                  type="button"
                  disabled={item.disabled}
                  onPointerDown={e => {
                    if (item.disabled) return;
                    e.preventDefault(); // keep input focused so blur doesn't fire before onChange
                    onChange(item.id);
                    setQuery(item.name);
                    setOpen(false);
                  }}
                  style={depth > 0 ? { paddingRight: `${0.75 + depth * 1.25}rem` } : undefined}
                  className={`w-full flex items-center gap-1 text-right px-3 py-2 text-sm ${
                    item.disabled
                      ? "text-gray-400 dark:text-gray-600 cursor-not-allowed"
                      : `hover:bg-gray-50 dark:hover:bg-gray-700 ${
                          value === item.id ? "font-semibold text-indigo-600 dark:text-indigo-300" : "text-gray-700 dark:text-gray-200"
                        }`
                  }`}
                >
                  {depth > 0 && <span className="text-gray-300 dark:text-gray-600 text-xs select-none">└</span>}
                  {item.name}
                </button>
              </li>
            );
          })}
        </ul>,
        document.body
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- --run Combobox` (from `frontend/`)
Expected: PASS — 8 tests

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Combobox.tsx frontend/src/components/Combobox.test.tsx
git commit -m "feat: add shared searchable Combobox component"
```

---

### Task 2: `ShiftTemplateFormModal` — use the shared Combobox

**Files:**
- Modify: `frontend/src/components/ShiftTemplateFormModal.tsx:1-174`

- [ ] **Step 1: Remove the private `Combobox` and import the shared one**

Delete lines 107-174 (the entire private `Combobox` function, from the comment `// Combobox with Fuse.js...` through its closing `}`).

Delete the now-unused imports at the top (`Fuse`, `useLayoutEffect`, `createPortal` are only used by the deleted component — `useEffect`, `useRef`, `useState` are still used elsewhere in the file):

```tsx
// before (lines 1-3)
import Fuse from "fuse.js";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
```

```tsx
// after
import { useEffect, useState } from "react";
```

Add the import for the shared component, alongside the other local component imports:

```tsx
import DutyTypeFormModal from "./DutyTypeFormModal";
import LocationFormModal from "./LocationFormModal";
import Combobox from "./Combobox";
```

- [ ] **Step 2: Run the frontend test suite to confirm nothing else broke**

Run: `npm test -- --run` (from `frontend/`)
Expected: PASS — same pass count as baseline (38 tests, since no test file targets this component)

- [ ] **Step 3: Run lint**

Run: `npm run lint` (from `frontend/`)
Expected: 0 warnings/errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ShiftTemplateFormModal.tsx
git commit -m "refactor: ShiftTemplateFormModal uses shared Combobox component"
```

---

### Task 3: `ShiftFormModal` — duty type + location selects

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx:1, 86-122`

- [ ] **Step 1: Add the import**

```tsx
// line 1, before the existing imports
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the duty-type select**

```tsx
// before (lines 86-89)
              <label className="block text-sm">
                {t("shifts.duty_type")}
                <select value={dtId} onChange={e => setDtId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
                  {dutyTypes.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
```

```tsx
// after
              <div>
                <span className="text-sm block mb-0.5">{t("shifts.duty_type")}</span>
                <Combobox items={dutyTypes} value={dtId} onChange={setDtId} />
              </div>
```

- [ ] **Step 3: Replace the location select**

```tsx
// before (lines 117-121)
                {addingLocation ? (
                  ...
                ) : (
                  <select value={locId} onChange={e => setLocId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
                    {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                  </select>
                )}
```

```tsx
// after
                {addingLocation ? (
                  ...
                ) : (
                  <Combobox items={locations} value={locId} onChange={setLocId} />
                )}
```

(Leave the `addingLocation ? (...)` branch's inner JSX exactly as-is — only the `else` branch's `<select>` is replaced.)

- [ ] **Step 4: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx
git commit -m "feat: searchable dropdowns for duty type and location in new-shift modal"
```

---

### Task 4: `DutyManagementPage` — soldier select

**Files:**
- Modify: `frontend/src/pages/DutyManagementPage.tsx:1, 127-131`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "../components/Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
      <label className="block text-sm">{t("duty_management.soldier")}
        <select className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={soldierId} onChange={(e) => setSoldierId(e.target.value)} data-testid="dm-soldier">
          {soldiers.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
        </select>
      </label>
```

```tsx
// after
      <div className="block text-sm">
        <span className="block mb-0.5">{t("duty_management.soldier")}</span>
        <Combobox
          items={soldiers.map(s => ({ id: s.id, name: s.full_name }))}
          value={soldierId}
          onChange={setSoldierId}
          testId="dm-soldier"
        />
      </div>
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/DutyManagementPage.tsx
git commit -m "feat: searchable soldier dropdown in duty management"
```

---

### Task 5: `AlgorithmProposalTable` — batch filter select

**Files:**
- Modify: `frontend/src/components/AlgorithmProposalTable.tsx:1, 300-310`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
            {hasBatches && (
              <select
                value={batchFilter ?? ""}
                onChange={e => setBatchFilter(e.target.value === "" ? null : Number(e.target.value))}
                className="text-xs border dark:border-gray-600 rounded px-2 py-1 dark:bg-gray-700 dark:text-gray-100"
              >
                <option value="">כל האצוות</option>
                {batchIndices.map(bi => (
                  <option key={bi} value={bi}>אצווה {bi + 1}</option>
                ))}
              </select>
            )}
```

```tsx
// after
            {hasBatches && (
              <div className="w-40">
                <Combobox
                  items={batchIndices.map(bi => ({ id: String(bi), name: `אצווה ${bi + 1}` }))}
                  value={batchFilter === null ? "" : String(batchFilter)}
                  onChange={id => setBatchFilter(id === "" ? null : Number(id))}
                  placeholder="כל האצוות"
                />
              </div>
            )}
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AlgorithmProposalTable.tsx
git commit -m "feat: searchable batch filter dropdown in algorithm proposals"
```

---

### Task 6: `AlgorithmRunForm` — duty type filter select

**Files:**
- Modify: `frontend/src/components/AlgorithmRunForm.tsx:1, 134-141`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
            <select
              value={filterDutyTypeId}
              onChange={e => setFilterDutyTypeId(e.target.value)}
              className="border rounded p-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            >
              <option value="">כל הסוגים</option>
              {dutyTypes.map(dt => <option key={dt.id} value={dt.id}>{dt.name}</option>)}
            </select>
```

```tsx
// after
            <div className="w-40">
              <Combobox
                items={dutyTypes}
                value={filterDutyTypeId}
                onChange={setFilterDutyTypeId}
                placeholder="כל הסוגים"
              />
            </div>
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: searchable duty type filter dropdown in algorithm run form"
```

---

### Task 7: `ProfilePage` — rank request select + commander-scope node select

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx:20, 236-250, 450-465`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "../components/Combobox";
```

- [ ] **Step 2: Replace the rank-request select (group support for enlisted/officers)**

```tsx
// before
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.rank")}</label>
            <select value={rankReq} onChange={e => setRankReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
              <option value="">—</option>
              {ranks.enlisted.length > 0 && (
                <optgroup label={t("soldier_profile.enlisted")}>
                  {ranks.enlisted.map(r => <option key={r} value={r}>{r}</option>)}
                </optgroup>
              )}
              {ranks.officers.length > 0 && (
                <optgroup label={t("soldier_profile.officers")}>
                  {ranks.officers.map(r => <option key={r} value={r}>{r}</option>)}
                </optgroup>
              )}
            </select>
            <button type="button" onClick={() => requestUpdate("rank", rankReq)} disabled={!rankReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
```

```tsx
// after
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.rank")}</label>
            <div className="flex-1">
              <Combobox
                items={[
                  ...ranks.enlisted.map(r => ({ id: r, name: r, group: t("soldier_profile.enlisted") })),
                  ...ranks.officers.map(r => ({ id: r, name: r, group: t("soldier_profile.officers") })),
                ]}
                value={rankReq}
                onChange={setRankReq}
                placeholder="—"
              />
            </div>
            <button type="button" onClick={() => requestUpdate("rank", rankReq)} disabled={!rankReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
```

- [ ] **Step 3: Replace the commander-scope node select**

```tsx
// before
              <select
                value={addNodeId}
                onChange={(e) => setAddNodeId(e.target.value)}
                required
                className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 min-w-[180px]"
              >
                <option value="">— בחר ענף —</option>
                {sortNodesByTree(hierarchyNodes).map(({ node, depth }) => (
                  <option key={node.id} value={node.id}>
                    {indentedNodeLabel(node, depth)}
                  </option>
                ))}
              </select>
```

```tsx
// after
              <div className="min-w-[180px]">
                <Combobox
                  items={sortNodesByTree(hierarchyNodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                  value={addNodeId}
                  onChange={setAddNodeId}
                  placeholder="— בחר ענף —"
                />
              </div>
```

`indentedNodeLabel` is no longer used in this file after this change — leave the `sortNodesByTree` import, but check whether `indentedNodeLabel` is still referenced elsewhere in the file before removing it from the import line.

- [ ] **Step 4: Remove `indentedNodeLabel` from the import if now unused**

```tsx
// before
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
```

```tsx
// after (only if `indentedNodeLabel` has zero remaining references in this file)
import { sortNodesByTree } from "../utils/sortNodesByTree";
```

- [ ] **Step 5: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings (lint will catch an unused import if Step 4 was skipped incorrectly)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "feat: searchable dropdowns for rank request and commander-scope node in profile"
```

---

### Task 8: `MyRequestsPage` — exemption type select

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx:1, 233-252`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "../components/Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
                <select
                  className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={erTypeId}
                  onChange={(e) => {
                    const typeId = e.target.value;
                    setErTypeId(typeId);
                    setUploadFiles([]); setUploadSizeErrors([]);
                    const type = exemptionTypes.find(et => et.id === typeId);
                    setErMedical(type?.is_medical ?? false);
                  }}
                  required
                  data-testid="er-type"
                >
                  <option value="">— {t("exemption_requests.type")} —</option>
                  {exemptionTypes.map((et) => (
                    <option key={et.id} value={et.id}>
                      {et.name}{et.is_medical ? " 🏥" : ""}
                    </option>
                  ))}
                </select>
```

```tsx
// after
                <Combobox
                  items={exemptionTypes.map(et => ({ id: et.id, name: `${et.name}${et.is_medical ? " 🏥" : ""}` }))}
                  value={erTypeId}
                  onChange={(typeId) => {
                    setErTypeId(typeId);
                    setUploadFiles([]); setUploadSizeErrors([]);
                    const type = exemptionTypes.find(et => et.id === typeId);
                    setErMedical(type?.is_medical ?? false);
                  }}
                  placeholder={`— ${t("exemption_requests.type")} —`}
                  testId="er-type"
                />
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx
git commit -m "feat: searchable exemption type dropdown in my-requests page"
```

---

### Task 9: `TeamHierarchyPage` — onboarding node select

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx:11, 89-95`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "../components/Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
            <label className="block">
              <span className="text-xs">{t("team.title")}</span>
              <select className="block border rounded p-1 text-gray-900 dark:text-white bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="onboard-node">
                <option value="">—</option>
                {sortNodesByTree(nodes).map(({ node, depth }) => <option key={node.id} value={node.id}>{indentedNodeLabel(node, depth)}</option>)}
              </select>
            </label>
```

```tsx
// after
            <label className="block">
              <span className="text-xs">{t("team.title")}</span>
              <Combobox
                items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                value={nodeId}
                onChange={setNodeId}
                placeholder="—"
                testId="onboard-node"
              />
            </label>
```

- [ ] **Step 3: Remove `indentedNodeLabel` from the import if now unused in this file**

```tsx
// before
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
```

```tsx
// after (only if `indentedNodeLabel` has zero remaining references in this file)
import { sortNodesByTree } from "../utils/sortNodesByTree";
```

- [ ] **Step 4: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TeamHierarchyPage.tsx
git commit -m "feat: searchable hierarchy node dropdown in onboarding form"
```

---

### Task 10: `RegisterPage` — rank select

**Files:**
- Modify: `frontend/src/pages/RegisterPage.tsx:1-12, 150-154`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "../components/Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
            <label className="block text-sm">דרגה
              <select className="mt-1 block w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={form.rank} onChange={e => set("rank", e.target.value)}>
                <option value="">בחר</option>
                {ALL_RANKS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
```

```tsx
// after
            <label className="block text-sm">דרגה
              <Combobox
                items={ALL_RANKS.map(r => ({ id: r, name: r }))}
                value={form.rank}
                onChange={v => set("rank", v)}
                placeholder="בחר"
              />
            </label>
```

(The gender select directly above stays untouched — 2 fixed options, native `<select>` per the design.)

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RegisterPage.tsx
git commit -m "feat: searchable rank dropdown in registration form"
```

---

### Task 11: `DismissalModal` — covering-reserve assignment select

**Files:**
- Modify: `frontend/src/components/DismissalModal.tsx:1-5, 139-153`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
          <select
            value={selectedReserveId}
            onChange={e => setSelectedReserveId(e.target.value)}
            className="border border-gray-300 dark:border-gray-600 rounded-lg p-2 w-full text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-amber-300 focus:border-amber-400 outline-none"
          >
            {reserveOptions.length === 0 && <option value="">{t("dismiss_modal.no_reserves")}</option>}
            {reserveOptions.map(a => (
              <option key={a.assignment_id} value={a.assignment_id}>
                {a.soldier_name}
                {a.assignment_id === primary.reserve_assignment_id ? ` (${t("reserve_standby")})` : ""}
              </option>
            ))}
          </select>
```

```tsx
// after
          {reserveOptions.length === 0 ? (
            <p className="text-sm text-gray-400 italic">{t("dismiss_modal.no_reserves")}</p>
          ) : (
            <Combobox
              items={reserveOptions.map(a => ({
                id: a.assignment_id,
                name: a.soldier_name + (a.assignment_id === primary.reserve_assignment_id ? ` (${t("reserve_standby")})` : ""),
              }))}
              value={selectedReserveId}
              onChange={setSelectedReserveId}
            />
          )}
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/DismissalModal.tsx
git commit -m "feat: searchable reserve assignment dropdown in dismissal modal"
```

---

### Task 12: `EntriesExitsPanel` — exemption type select + target node select

**Files:**
- Modify: `frontend/src/components/EntriesExitsPanel.tsx:1-9, 94-99, 119-124`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the exemption-type select**

```tsx
// before
              <select className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exemptionTypeId} onChange={(e) => setExemptionTypeId(e.target.value)}>
                <option value="">{t("command_dashboard.none")}</option>
                {exemptionTypes.map((et) => (
                  <option key={et.id} value={et.id}>{et.name}</option>
                ))}
              </select>
```

```tsx
// after
              <Combobox
                items={exemptionTypes.map(et => ({ id: et.id, name: et.name }))}
                value={exemptionTypeId}
                onChange={setExemptionTypeId}
                placeholder={t("command_dashboard.none")}
              />
```

- [ ] **Step 3: Replace the target-node select**

```tsx
// before
              <select className="w-full border rounded p-2 text-gray-900 dark:text-white bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600" value={targetNodeId} onChange={(e) => setTargetNodeId(e.target.value)}>
                <option value="">{t("command_dashboard.none")}</option>
                {sortNodesByTree(nodes).map(({ node, depth }) => (
                  <option key={node.id} value={node.id}>{indentedNodeLabel(node, depth)}</option>
                ))}
              </select>
```

```tsx
// after
              <Combobox
                items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                value={targetNodeId}
                onChange={setTargetNodeId}
                placeholder={t("command_dashboard.none")}
              />
```

- [ ] **Step 4: Remove `indentedNodeLabel` from the import if now unused in this file**

```tsx
// before
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
```

```tsx
// after (only if `indentedNodeLabel` has zero remaining references in this file)
import { sortNodesByTree } from "../utils/sortNodesByTree";
```

- [ ] **Step 5: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EntriesExitsPanel.tsx
git commit -m "feat: searchable dropdowns for exemption type and target node in command dashboard"
```

---

### Task 13: `ExemptionsPanel` — grant type select

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx:1-6, 209-212`
- Test: `frontend/src/components/ExemptionsPanel.test.tsx` (existing — verify it still passes, no changes expected)

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
          <select className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={typeId} onChange={(e) => setTypeId(e.target.value)} required data-testid="grant-type">
            <option value="">{t("exemptions.type")}</option>
            {types.map((tp) => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
```

```tsx
// after
          <Combobox
            items={types.map(tp => ({ id: tp.id, name: tp.name }))}
            value={typeId}
            onChange={setTypeId}
            placeholder={t("exemptions.type")}
            testId="grant-type"
          />
```

- [ ] **Step 3: Run the existing test for this file plus the full suite and lint**

Run: `npm test -- --run ExemptionsPanel && npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings — `ExemptionsPanel.test.tsx` doesn't touch `grant-type`, so it's unaffected

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ExemptionsPanel.tsx
git commit -m "feat: searchable exemption type dropdown in grant form"
```

---

### Task 14: `SoldierEditModal` — hierarchy node select

**Files:**
- Modify: `frontend/src/components/SoldierEditModal.tsx:1-5, 50-56`

- [ ] **Step 1: Add the import, drop `indentedNodeLabel`**

```tsx
// before
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
```

```tsx
// after
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
          <label className="block">
            <span className="text-xs">{t("team.title")}</span>
            <select className="border rounded p-1 w-full text-gray-900 dark:text-white bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600" value={hierarchyNodeId} onChange={(e) => setHierarchyNodeId(e.target.value)} data-testid="edit-soldier-node">
              <option value="">—</option>
              {sortNodesByTree(nodes).map(({ node, depth }) => <option key={node.id} value={node.id}>{indentedNodeLabel(node, depth)}</option>)}
            </select>
          </label>
```

```tsx
// after
          <label className="block">
            <span className="text-xs">{t("team.title")}</span>
            <Combobox
              items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
              value={hierarchyNodeId}
              onChange={setHierarchyNodeId}
              placeholder="—"
              testId="edit-soldier-node"
            />
          </label>
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SoldierEditModal.tsx
git commit -m "feat: searchable hierarchy node dropdown in soldier edit modal"
```

---

### Task 15: `ReserveDismissalModal` — candidate select (disabled rows for called-up)

**Files:**
- Modify: `frontend/src/components/ReserveDismissalModal.tsx:1, 156-177`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the select**

```tsx
// before
              <select
                value={selectedCandidateId}
                onChange={e => setSelectedCandidateId(e.target.value)}
                className="border border-gray-300 dark:border-gray-600 rounded-lg p-2 w-full text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-amber-300 focus:border-amber-400 outline-none"
              >
                {(() => {
                  const minDist = Math.min(...candidates.map(c => c.distance));
                  return candidates.map((c) => {
                    const a = assigneeById[c.assignment_id];
                    const name = a?.soldier_name ?? c.soldier_id;
                    const calledUp = c.called_up_from != null;
                    const recommended = c.distance === minDist;
                    return (
                      <option key={c.assignment_id} value={c.assignment_id} disabled={calledUp}>
                        {recommended ? "★ " : ""}{name} — {t("distance_label", "מרחק")}: {c.distance}{calledUp ? ` (${t("reserve_called_up", "בהקפצה")})` : ""}
                      </option>
                    );
                  });
                })()}
              </select>
```

```tsx
// after
              <Combobox
                items={(() => {
                  const minDist = Math.min(...candidates.map(c => c.distance));
                  return candidates.map((c) => {
                    const a = assigneeById[c.assignment_id];
                    const name = a?.soldier_name ?? c.soldier_id;
                    const calledUp = c.called_up_from != null;
                    const recommended = c.distance === minDist;
                    return {
                      id: c.assignment_id,
                      name: `${recommended ? "★ " : ""}${name} — ${t("distance_label", "מרחק")}: ${c.distance}${calledUp ? ` (${t("reserve_called_up", "בהקפצה")})` : ""}`,
                      disabled: calledUp,
                    };
                  });
                })()}
                value={selectedCandidateId}
                onChange={setSelectedCandidateId}
              />
```

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ReserveDismissalModal.tsx
git commit -m "feat: searchable candidate dropdown in reserve dismissal modal"
```

---

### Task 16: `UnifiedSoldierModal` — hierarchy node select + rank select

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx:1-11, 293-298, 378-392`

- [ ] **Step 1: Add the import**

```tsx
import Combobox from "./Combobox";
```

- [ ] **Step 2: Replace the hierarchy node select**

```tsx
// before
                <select className="border rounded p-1 w-full text-gray-900 dark:text-white bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600" value={hierarchyNodeId} onChange={(e) => setHierarchyNodeId(e.target.value)} data-testid="edit-soldier-node">
                  <option value="">—</option>
                  {sortNodesByTree(nodes).map(({ node, depth }) => <option key={node.id} value={node.id}>{indentedNodeLabel(node, depth)}</option>)}
                </select>
```

```tsx
// after
                <Combobox
                  items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                  value={hierarchyNodeId}
                  onChange={setHierarchyNodeId}
                  placeholder="—"
                  testId="edit-soldier-node"
                />
```

- [ ] **Step 3: Replace the rank select (group support for enlisted/officers)**

```tsx
// before
                <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileRank} onChange={(e) => setProfileRank(e.target.value)}>
                  <option value="">—</option>
                  {rankOptions.enlisted.length > 0 && (
                    <optgroup label={t("soldier_profile.enlisted")}>
                      {rankOptions.enlisted.map((r) => <option key={r} value={r}>{r}</option>)}
                    </optgroup>
                  )}
                  {rankOptions.officers.length > 0 && (
                    <optgroup label={t("soldier_profile.officers")}>
                      {rankOptions.officers.map((r) => <option key={r} value={r}>{r}</option>)}
                    </optgroup>
                  )}
                </select>
```

```tsx
// after
                <Combobox
                  items={[
                    ...rankOptions.enlisted.map(r => ({ id: r, name: r, group: t("soldier_profile.enlisted") })),
                    ...rankOptions.officers.map(r => ({ id: r, name: r, group: t("soldier_profile.officers") })),
                  ]}
                  value={profileRank}
                  onChange={setProfileRank}
                  placeholder="—"
                />
```

(The gender select directly above the rank select stays untouched — 2 fixed options, native `<select>` per the design.)

- [ ] **Step 4: Remove `indentedNodeLabel` from the import if now unused in this file**

```tsx
// before
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
```

```tsx
// after (only if `indentedNodeLabel` has zero remaining references in this file)
import { sortNodesByTree } from "../utils/sortNodesByTree";
```

- [ ] **Step 5: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "feat: searchable dropdowns for hierarchy node and rank in unified soldier modal"
```

---

### Task 17: `UnitCalendarPage` — replace bespoke `NodeSearchDropdown` with shared Combobox

**Files:**
- Modify: `frontend/src/pages/UnitCalendarPage.tsx`

- [ ] **Step 1: Remove the private `NodeSearchDropdown` component and its now-unused imports**

Delete lines 35-125 (the entire `NodeSearchDropdownProps` interface and `NodeSearchDropdown` function).

```tsx
// before (line 1)
import { useEffect, useMemo, useRef, useState } from "react";
```

```tsx
// after — useRef is only used inside the deleted component
import { useEffect, useMemo, useState } from "react";
```

Add the import for the shared component:

```tsx
import Combobox from "../components/Combobox";
```

- [ ] **Step 2: Replace the usage**

```tsx
// before
        <NodeSearchDropdown
          nodes={nodes}
          depthMap={depthMap}
          value={nodeId}
          onChange={setNodeId}
        />
```

```tsx
// after
        <div className="w-72">
          <Combobox
            items={nodes.map((n) => ({ id: n.id, name: n.name, depth: depthMap.get(n.id) ?? 0 }))}
            value={nodeId}
            onChange={setNodeId}
          />
        </div>
```

`nodes` is already in `treeOrder` (DFS order, set in the `fetchFullTree().then(...)` callback), so passing it straight to `Combobox` preserves the same ordering `NodeSearchDropdown` displayed. `depthMap` (built by the existing `buildDepthMap` helper) is unchanged and still needed for `depth`.

- [ ] **Step 3: Run tests and lint**

Run: `npm test -- --run && npm run lint` (from `frontend/`)
Expected: PASS, 0 lint warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/UnitCalendarPage.tsx
git commit -m "refactor: UnitCalendarPage node selector uses shared Combobox component"
```

---

### Task 18: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full frontend test suite**

Run: `npm test -- --run` (from `frontend/`)
Expected: PASS, test count ≥ baseline (38) + 8 new `Combobox` tests = 46

- [ ] **Step 2: Run lint across the whole frontend**

Run: `npm run lint` (from `frontend/`)
Expected: 0 warnings (zero-warnings is enforced per `CLAUDE.md`)

- [ ] **Step 3: Confirm no native `<select>` remains in any converted file**

Run (from `frontend/`):
```bash
grep -n "<select" src/components/ShiftFormModal.tsx src/components/ShiftTemplateFormModal.tsx \
  src/pages/DutyManagementPage.tsx src/components/AlgorithmProposalTable.tsx src/components/AlgorithmRunForm.tsx \
  src/pages/ProfilePage.tsx src/pages/MyRequestsPage.tsx src/pages/TeamHierarchyPage.tsx \
  src/components/DismissalModal.tsx src/components/EntriesExitsPanel.tsx src/components/ExemptionsPanel.tsx \
  src/components/SoldierEditModal.tsx src/components/ReserveDismissalModal.tsx src/components/UnifiedSoldierModal.tsx \
  src/pages/UnitCalendarPage.tsx
```
Expected: only the intentionally-native selects remain — `ProfilePage.tsx` (gender, depth-levels filter), `RegisterPage.tsx` (gender), `UnifiedSoldierModal.tsx` (gender). `RegisterPage.tsx` itself isn't in this grep list since only its rank select was converted; if you want to double check it, add it to the list and confirm only the gender `<select>` shows up.

- [ ] **Step 4: No commit needed — this task is verification only**

