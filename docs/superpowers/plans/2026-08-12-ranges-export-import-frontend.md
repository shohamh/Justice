# Ranges Export/Import — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the five new ranges import sheets (`range_locations`, `range_events`, `range_assignments`, `soldier_range_qualifications`, `range_excusal_requests` — added to the backend in the companion backend plan) in the review UI, the unified export page, and the ranges page.

**Architecture:** `ImportSessionReviewPage.tsx` gets 5 new tabs, each following the closest existing tab's exact established pattern (`duty_locations` for `range_locations`; `duty_shifts` minus node-quotas for `range_events`; `assignments` for `range_assignments`; `personal_constraints` for the two approval-workflow sheets). `ExportPage.tsx` gets 3 new checkboxes wired to the existing `/config/export` and `/import/export` calls (no new export mechanism — `/approvals/export` already exports unconditionally and needs no frontend change). `RangesPage.tsx` and `ImportUploadPage.tsx` get small discoverability links to the existing unified pages.

**Tech Stack:** React, TypeScript, TanStack Query, Vitest + Testing Library.

## Global Constraints

- Every new tab must reuse the shared helpers already defined in `ImportSessionReviewPage.tsx` — `StatusChip`, `setFieldOverride`, `setRowAction`, `currentSelection`, `setDetailModal`/`ImportRowDetailModal` — exactly as the existing tabs do. Do not introduce parallel helpers.
- Per the corresponding backend plan's scoping decision, `range_events`/`range_assignments` do **not** get the Combobox unresolved-node-picker treatment that `soldiers`/`duty_shifts` quotas have — unresolved `hierarchy_node_name`/`range_location_name` are shown as plain text (red on error), matching how `duty_shifts`' own `duty_location_name` and `assignments`' `duty_location_name`/`personal_number` are already displayed today. This keeps the change from touching the shared `handlePick`/`sameNameCount` cross-tab logic.
- `soldier_range_qualifications` is plain create/update data (no `status`/approval workflow — the backing DB model has no such column); `range_excusal_requests` is the one approval-workflow-shaped sheet among the five, with a `status` dropdown (`pending`/`approved`/`rejected`) matching `personal_constraints`'s exact treatment.
- All new sheets are always-"new"-or-"error" like `duty_shifts`/`assignments` (`range_events`, `range_assignments`) or update-by-key like `duty_locations`/`personal_constraints` (`range_locations`, `soldier_range_qualifications`, `range_excusal_requests`) — never introduce a `skip`-only or different action model.
- `RangeType` values for any `<select>`: `laser`/`live`/`alal`. `RangeEventStatus`: `planned`/`completed`/`cancelled`. `RangeAttendanceStatus`: `pending`/`present`/`no_show`. `RangeExcusalStatus`: `pending`/`approved`/`rejected`.

---

## File Structure

- Modify `frontend/src/api/importSessions.ts` — add 5 row interfaces, extend `ParsedState` and `SessionSummary.row_summary`.
- Modify `frontend/src/pages/ImportSessionReviewPage.tsx` — extend `TabKey`/`GroupKey`, destructure the 5 new arrays, add 5 tab buttons, add 5 tab-content blocks.
- Modify `frontend/src/pages/ImportSessionReviewPage.test.tsx` — extend `makeDraftDetail` with the 5 new empty arrays; add per-tab tests.
- Modify `frontend/src/pages/planning/ExportPage.tsx` — add `range_locations` to `CONFIG_SHEET_OPTIONS`, `range_events`/`range_assignments` to `DATA_SHEET_OPTIONS`.
- Modify `frontend/src/pages/planning/ExportPage.test.tsx` — extend the checkbox-presence test.
- Modify `frontend/src/pages/RangesPage.tsx` — add "ייצוא"/"ייבוא" links.
- Modify `frontend/src/pages/RangesPage.test.tsx` — assert the links render for a manager.
- Modify `frontend/src/pages/ImportUploadPage.tsx` — update the sheet-name hint text.

---

### Task 1: Types — extend `api/importSessions.ts`

**Files:**
- Modify: `frontend/src/api/importSessions.ts`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx` (fixture only — required for the existing suite to keep type-checking; see Step 2)

**Interfaces:**
- Produces: `RangeLocationImportRow`, `RangeEventImportRow`, `RangeAssignmentImportRow`, `SoldierRangeQualificationImportRow`, `RangeExcusalRequestImportRow` (all `extends RowBase`); `ParsedState` gains `range_locations`, `range_events`, `range_assignments`, `soldier_range_qualifications`, `range_excusal_requests`; `SessionSummary["row_summary"]` gains the same 5 keys.

- [ ] **Step 1: Add the 5 interfaces and extend `ParsedState`/`SessionSummary`**

Add after `AssignmentRow` in `importSessions.ts`:

```typescript
export interface RangeLocationImportRow extends RowBase {
  name: string;
  active: boolean | null;
  existing_id: string | null;
}

export interface RangeEventImportRow extends RowBase {
  hierarchy_node_name: string | null;
  resolved_hierarchy_node_id: string | null;
  range_type: string;
  date: string;
  range_location_name: string;
  resolved_range_location_id: string | null;
  required_count: number;
  reserve_count: number;
  start_time: string | null;
  end_time: string | null;
  arrival_instructions: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  notes: string | null;
  status: string;
}

export interface RangeAssignmentImportRow extends RowBase {
  personal_number: string;
  full_name: string;
  range_type: string;
  date: string;
  range_location_name: string;
  is_reserve: boolean;
  is_draft: boolean;
  attendance_status: string;
  note: string | null;
  resolved_soldier_id: string | null;
  resolved_range_event_id: string | null;
  matched_session_row: number | null;
}

export interface SoldierRangeQualificationImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  range_type: string;
  valid_until: string;
  existing_id: string | null;
}

export interface RangeExcusalRequestImportRow extends RowBase {
  id: string | null;
  soldier_personal_number: string;
  resolved_soldier_id: string | null;
  requested_by_personal_number: string | null;
  resolved_requested_by_id: string | null;
  hierarchy_node_name: string | null;
  range_type: string;
  date: string;
  range_location_name: string;
  resolved_range_event_id: string | null;
  resolved_range_assignment_id: string | null;
  reason: string | null;
  status: string;
  decided_by_personal_number: string | null;
  resolved_decided_by_id: string | null;
  decision_note: string | null;
  existing_id: string | null;
}
```

Add to `ParsedState` (alongside `assignments: AssignmentRow[];`):

```typescript
  range_locations: RangeLocationImportRow[];
  range_events: RangeEventImportRow[];
  range_assignments: RangeAssignmentImportRow[];
  soldier_range_qualifications: SoldierRangeQualificationImportRow[];
  range_excusal_requests: RangeExcusalRequestImportRow[];
```

Add to `SessionSummary["row_summary"]` (alongside `assignments: number;`):

```typescript
    range_locations: number;
    range_events: number;
    range_assignments: number;
    soldier_range_qualifications: number;
    range_excusal_requests: number;
```

- [ ] **Step 2: Update the shared test fixture so the existing suite still compiles**

In `ImportSessionReviewPage.test.tsx`'s `makeDraftDetail`, add the 5 new empty arrays to the `parsed_state` object literal (alongside `swap_requests: [],`):

```typescript
      range_locations: [],
      range_events: [],
      range_assignments: [],
      soldier_range_qualifications: [],
      range_excusal_requests: [],
```

- [ ] **Step 3: Run typecheck and the existing test suite**

Run: `cd frontend && npm run typecheck && npm test -- ImportSessionReviewPage`
Expected: PASS (no new tests yet — this only verifies the type changes don't break existing code)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add range import row types"
```

---

### Task 2: Tab plumbing — `TabKey`/`GroupKey`, destructuring, tab buttons

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: Task 1's types.
- Produces: `TabKey`/`GroupKey` include the 5 new sheet names; the component destructures the 5 new arrays from `detail.parsed_state`; 5 new tab buttons with row counts render in the tab bar. No tab content yet (empty `{tab === "range_locations" && null}` placeholders are **not** added — the tab buttons simply have no matching content block until Tasks 3–7 add them, which is fine since a user can't select a tab with zero rows meaningfully anyway and each subsequent task adds its own content block immediately).

- [ ] **Step 1: Write the failing test**

Add to `ImportSessionReviewPage.test.tsx`, inside the `describe("ImportSessionReviewPage", ...)` block:

```typescript
  it("shows tab counts for the new range sheets", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_locations = [
      { row: 2, action: "new", errors: [], name: "מטווח דרומי", active: true, existing_id: null },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    expect(screen.getByText("מיקומי מטווח (1)")).toBeInTheDocument();
    expect(screen.getByText("מטווחים (0)")).toBeInTheDocument();
    expect(screen.getByText("שיבוצי מטווח (0)")).toBeInTheDocument();
    expect(screen.getByText("כשירויות מטווח (0)")).toBeInTheDocument();
    expect(screen.getByText("בקשות פטור ממטווח (0)")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "shows tab counts for the new range sheets"`
Expected: FAIL (tab labels don't exist)

- [ ] **Step 3: Wire in the 5 sheets**

In `ImportSessionReviewPage.tsx`, add the 5 new imports to the `import { ... } from "../api/importSessions"` block: `type RangeLocationImportRow`, `type RangeEventImportRow`, `type RangeAssignmentImportRow`, `type SoldierRangeQualificationImportRow`, `type RangeExcusalRequestImportRow`.

Add to `TabKey` and `GroupKey` (both unions, identical additions to each):

```typescript
  | "range_locations"
  | "range_events"
  | "range_assignments"
  | "soldier_range_qualifications"
  | "range_excusal_requests";
```

Add to the destructuring block (alongside `swap_requests,`):

```typescript
    range_locations,
    range_events,
    range_assignments,
    soldier_range_qualifications,
    range_excusal_requests,
```

Add to the tab-list array (alongside `["swap_requests", ...]`):

```typescript
              ["range_locations", `מיקומי מטווח (${range_locations.length})`],
              ["range_events", `מטווחים (${range_events.length})`],
              ["range_assignments", `שיבוצי מטווח (${range_assignments.length})`],
              ["soldier_range_qualifications", `כשירויות מטווח (${soldier_range_qualifications.length})`],
              ["range_excusal_requests", `בקשות פטור ממטווח (${range_excusal_requests.length})`],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add range sheet tabs to import session review page"
```

---

### Task 3: `range_locations` tab content

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `RangeLocationImportRow` (Task 1); `range_locations` (Task 2).

- [ ] **Step 1: Write the failing test**

```typescript
  it("renders a range_locations row and toggles it to skip", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_locations = [
      { row: 2, action: "new", errors: [], name: "מטווח דרומי", active: true, existing_id: null },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("מיקומי מטווח (1)"));

    const row = await screen.findByDisplayValue("מטווח דרומי");
    const select = row.closest("tr")!.querySelector("select")!;
    fireEvent.change(select, { target: { value: "skip" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({ range_locations: expect.objectContaining({ "2": "skip" }) }),
      );
    });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "range_locations row"`
Expected: FAIL (no such tab content)

- [ ] **Step 3: Add the tab content block**

Add right after the `duty_locations` tab block closes (after line 1527 in the pre-existing file, i.e. immediately before the `hierarchy` tab block):

```tsx
        {tab === "range_locations" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">פעיל</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_locations.map((row: RangeLocationImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("range_locations", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.active === null ? "—" : row.active ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.active ?? false}
                            onChange={(e) => setFieldOverride("range_locations", row.row, "active", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "name", label: "שם", value: row.name, editable: { type: "text", onChange: (v) => setFieldOverride("range_locations", row.row, "name", v) } },
                                { key: "active", label: "פעיל", value: row.active, editable: { type: "checkbox", onChange: (v) => setFieldOverride("range_locations", row.row, "active", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_locations", row)}
                              onChange={(e) => setRowAction("range_locations", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add range_locations tab content"
```

---

### Task 4: `range_events` tab content

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `RangeEventImportRow` (Task 1); `range_events` (Task 2).

- [ ] **Step 1: Write the failing test**

```typescript
  it("renders a range_events row with editable required_count", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_events = [{
      row: 2, action: "new", errors: [],
      hierarchy_node_name: "מדור א", resolved_hierarchy_node_id: "node-1",
      range_type: "live", date: "2024-06-15",
      range_location_name: "מטווח דרומי", resolved_range_location_id: "loc-1",
      required_count: 10, reserve_count: 2, start_time: null, end_time: null,
      arrival_instructions: null, contact_name: null, contact_phone: null,
      notes: null, status: "planned",
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("מטווחים (1)"));

    const countInput = await screen.findByDisplayValue("10");
    fireEvent.blur(countInput, { target: { value: "12" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            range_events: expect.objectContaining({ "2": expect.objectContaining({ required_count: 12 }) }),
          }),
        }),
      );
    });
  });

  it("shows an unresolved range_events hierarchy_node_name in red", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_events = [{
      row: 2, action: "error", errors: ["יחידה לא מזוהה 'לא קיים'"],
      hierarchy_node_name: "לא קיים", resolved_hierarchy_node_id: null,
      range_type: "live", date: "2024-06-15",
      range_location_name: "מטווח דרומי", resolved_range_location_id: "loc-1",
      required_count: 10, reserve_count: 0, start_time: null, end_time: null,
      arrival_instructions: null, contact_name: null, contact_phone: null,
      notes: null, status: "planned",
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("מטווחים (1)"));

    await screen.findByText("שגיאה");
    expect(screen.getByText("לא קיים")).toHaveClass("text-red-600");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "range_events"`
Expected: FAIL

- [ ] **Step 3: Add the tab content block**

Add right after the `range_locations` block (Task 3) — before the `hierarchy` tab block:

```tsx
        {tab === "range_events" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">יחידה</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">תאריך</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_events.map((row: RangeEventImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedNode = !row.resolved_hierarchy_node_id;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={unresolvedNode ? "text-red-600" : ""}>{row.hierarchy_node_name}</span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.range_type : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.range_type}
                            onChange={(e) => setFieldOverride("range_events", row.row, "range_type", e.target.value)}
                          >
                            <option value="laser">לייזר</option>
                            <option value="live">חי</option>
                            <option value="alal">אלל</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.date : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.date}
                            onBlur={(iso) => setFieldOverride("range_events", row.row, "date", iso)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <span className={row.resolved_range_location_id ? "" : "text-red-600"}>{row.range_location_name}</span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.required_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.required_count}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "required_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reserve_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reserve_count}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "reserve_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("range_events", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "hierarchy_node_name", label: "יחידה", value: row.hierarchy_node_name },
                                { key: "resolved_hierarchy_node_id", label: "מזהה יחידה", value: row.resolved_hierarchy_node_id },
                                { key: "range_type", label: "סוג", value: row.range_type },
                                { key: "date", label: "תאריך", value: row.date, editable: { type: "date", onChange: (v) => setFieldOverride("range_events", row.row, "date", v) } },
                                { key: "range_location_name", label: "מיקום", value: row.range_location_name },
                                { key: "resolved_range_location_id", label: "מזהה מיקום", value: row.resolved_range_location_id },
                                { key: "required_count", label: "נדרש", value: row.required_count, editable: { type: "number", onChange: (v) => setFieldOverride("range_events", row.row, "required_count", v) } },
                                { key: "reserve_count", label: "רזרבה", value: row.reserve_count, editable: { type: "number", onChange: (v) => setFieldOverride("range_events", row.row, "reserve_count", v) } },
                                { key: "start_time", label: "שעת התחלה", value: row.start_time, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "start_time", v) } },
                                { key: "end_time", label: "שעת סיום", value: row.end_time, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "end_time", v) } },
                                { key: "arrival_instructions", label: "הנחיות הגעה", value: row.arrival_instructions, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "arrival_instructions", v) } },
                                { key: "contact_name", label: "איש קשר", value: row.contact_name, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "contact_name", v) } },
                                { key: "contact_phone", label: "טלפון איש קשר", value: row.contact_phone, editable: { type: "text", onChange: (v) => setFieldOverride("range_events", row.row, "contact_phone", v) } },
                                { key: "notes", label: "הערות", value: row.notes, editable: { type: "textarea", onChange: (v) => setFieldOverride("range_events", row.row, "notes", v) } },
                                { key: "status", label: "סטטוס מטווח", value: row.status },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_events", row)}
                              onChange={(e) => setRowAction("range_events", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add range_events tab content"
```

---

### Task 5: `range_assignments` tab content

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `RangeAssignmentImportRow` (Task 1); `range_assignments` (Task 2).

- [ ] **Step 1: Write the failing test**

```typescript
  it("renders a range_assignments row with an editable attendance_status", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_assignments = [{
      row: 2, action: "new", errors: [], warnings: [],
      personal_number: "12345", full_name: "ישראל ישראלי",
      range_type: "live", date: "2024-06-15", range_location_name: "מטווח דרומי",
      is_reserve: false, is_draft: false, attendance_status: "pending", note: null,
      resolved_soldier_id: "soldier-1", resolved_range_event_id: "event-1", matched_session_row: null,
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("שיבוצי מטווח (1)"));

    await screen.findByText("ישראל ישראלי");
    const select = screen.getByText("ישראל ישראלי").closest("tr")!.querySelectorAll("select")[0];
    fireEvent.change(select, { target: { value: "present" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            range_assignments: expect.objectContaining({ "2": expect.objectContaining({ attendance_status: "present" }) }),
          }),
        }),
      );
    });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "range_assignments row"`
Expected: FAIL

- [ ] **Step 3: Add the tab content block**

Add right after the `range_events` block (Task 4) — before the `hierarchy` tab block:

```tsx
        {tab === "range_assignments" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">תאריך</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">נוכחות</th>
                  <th className="text-right p-3">הערה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_assignments.map((row: RangeAssignmentImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>{row.full_name}</span>
                      </td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">{row.range_type}</td>
                      <td className="p-3">{row.date}</td>
                      <td className="p-3">
                        <span className={row.resolved_range_event_id || row.matched_session_row !== null ? "" : "text-red-600"}>
                          {row.range_location_name}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_reserve ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_reserve}
                            onChange={(e) => setFieldOverride("range_assignments", row.row, "is_reserve", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.attendance_status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.attendance_status}
                            onChange={(e) => setFieldOverride("range_assignments", row.row, "attendance_status", e.target.value)}
                          >
                            <option value="pending">ממתין</option>
                            <option value="present">נוכח</option>
                            <option value="no_show">לא הגיע</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.note ?? ""}
                            onBlur={(e) => setFieldOverride("range_assignments", row.row, "note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "personal_number", label: "מ\"א", value: row.personal_number },
                                { key: "full_name", label: "שם", value: row.full_name },
                                { key: "range_type", label: "סוג", value: row.range_type },
                                { key: "date", label: "תאריך", value: row.date },
                                { key: "range_location_name", label: "מיקום", value: row.range_location_name },
                                { key: "is_reserve", label: "רזרבה", value: row.is_reserve, editable: { type: "checkbox", onChange: (v) => setFieldOverride("range_assignments", row.row, "is_reserve", v) } },
                                { key: "is_draft", label: "טיוטה", value: row.is_draft, editable: { type: "checkbox", onChange: (v) => setFieldOverride("range_assignments", row.row, "is_draft", v) } },
                                { key: "attendance_status", label: "נוכחות", value: row.attendance_status },
                                { key: "note", label: "הערה", value: row.note, editable: { type: "text", onChange: (v) => setFieldOverride("range_assignments", row.row, "note", v) } },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "resolved_range_event_id", label: "מזהה מטווח", value: row.resolved_range_event_id },
                                { key: "matched_session_row", label: "שורה תואמת", value: row.matched_session_row },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_assignments", row)}
                              onChange={(e) => setRowAction("range_assignments", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add range_assignments tab content"
```

---

### Task 6: `soldier_range_qualifications` tab content

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `SoldierRangeQualificationImportRow` (Task 1); `soldier_range_qualifications` (Task 2).

- [ ] **Step 1: Write the failing test**

```typescript
  it("renders a soldier_range_qualifications row with an editable valid_until", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.soldier_range_qualifications = [{
      row: 2, action: "new", errors: [], id: null,
      soldier_personal_number: "12345", resolved_soldier_id: "soldier-1",
      range_type: "live", valid_until: "2025-01-01", existing_id: null,
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("כשירויות מטווח (1)"));

    const dateInput = await screen.findByDisplayValue("2025-01-01");
    fireEvent.blur(dateInput, { target: { value: "2026-01-01" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            soldier_range_qualifications: expect.objectContaining({ "2": expect.objectContaining({ valid_until: "2026-01-01" }) }),
          }),
        }),
      );
    });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "soldier_range_qualifications row"`
Expected: FAIL

- [ ] **Step 3: Add the tab content block**

Add right after the `range_assignments` block (Task 5) — before the `hierarchy` tab block:

```tsx
        {tab === "soldier_range_qualifications" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מ&quot;א חייל</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">בתוקף עד</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {soldier_range_qualifications.map((row: SoldierRangeQualificationImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>{row.soldier_personal_number}</span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.range_type : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.range_type}
                            onChange={(e) => setFieldOverride("soldier_range_qualifications", row.row, "range_type", e.target.value)}
                          >
                            <option value="laser">לייזר</option>
                            <option value="live">חי</option>
                            <option value="alal">אלל</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.valid_until : (
                          <DateInput
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.valid_until}
                            onBlur={(iso) => setFieldOverride("soldier_range_qualifications", row.row, "valid_until", iso)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "range_type", label: "סוג", value: row.range_type },
                                { key: "valid_until", label: "בתוקף עד", value: row.valid_until, editable: { type: "date", onChange: (v) => setFieldOverride("soldier_range_qualifications", row.row, "valid_until", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("soldier_range_qualifications", row)}
                              onChange={(e) => setRowAction("soldier_range_qualifications", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add soldier_range_qualifications tab content"
```

---

### Task 7: `range_excusal_requests` tab content

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `RangeExcusalRequestImportRow` (Task 1); `range_excusal_requests` (Task 2).

- [ ] **Step 1: Write the failing test**

```typescript
  it("renders a range_excusal_requests row with an editable status", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.range_excusal_requests = [{
      row: 2, action: "new", errors: [], id: null,
      soldier_personal_number: "12345", resolved_soldier_id: "soldier-1",
      requested_by_personal_number: "12345", resolved_requested_by_id: "soldier-1",
      hierarchy_node_name: "מדור א", range_type: "live", date: "2024-06-15",
      range_location_name: "מטווח דרומי", resolved_range_event_id: "event-1",
      resolved_range_assignment_id: "assignment-1", reason: "חופשה", status: "pending",
      decided_by_personal_number: null, resolved_decided_by_id: null,
      decision_note: null, existing_id: null,
    }];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");
    fireEvent.click(screen.getByText("בקשות פטור ממטווח (1)"));

    await screen.findByText("12345");
    const select = screen.getByText("12345").closest("tr")!.querySelector("select")!;
    fireEvent.change(select, { target: { value: "approved" } });

    await waitFor(() => {
      expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
        "session-1",
        expect.objectContaining({
          _field_overrides: expect.objectContaining({
            range_excusal_requests: expect.objectContaining({ "2": expect.objectContaining({ status: "approved" }) }),
          }),
        }),
      );
    });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ImportSessionReviewPage -t "range_excusal_requests row"`
Expected: FAIL

- [ ] **Step 3: Add the tab content block**

Add right after the `soldier_range_qualifications` block (Task 6) — before the `hierarchy` tab block:

```tsx
        {tab === "range_excusal_requests" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מ&quot;א חייל</th>
                  <th className="text-right p-3">מטווח</th>
                  <th className="text-right p-3">סיבה</th>
                  <th className="text-right p-3">סטטוס אישור</th>
                  <th className="text-right p-3">מחליט</th>
                  <th className="text-right p-3">הערת החלטה</th>
                  <th className="text-right p-3">פרטים</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {range_excusal_requests.map((row: RangeExcusalRequestImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        <span className={row.resolved_soldier_id ? "" : "text-red-600"}>{row.soldier_personal_number}</span>
                      </td>
                      <td className="p-3">
                        <span className={row.resolved_range_event_id ? "" : "text-red-600"}>
                          {row.hierarchy_node_name} · {row.range_type} · {row.date}
                        </span>
                      </td>
                      <td className="p-3">
                        {readOnly ? row.reason ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.reason ?? ""}
                            onBlur={(e) => setFieldOverride("range_excusal_requests", row.row, "reason", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("range_excusal_requests", row.row, "status", e.target.value)}
                          >
                            <option value="pending">ממתין</option>
                            <option value="approved">מאושר</option>
                            <option value="rejected">נדחה</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">
                        {row.decided_by_personal_number ? (
                          <span className={row.resolved_decided_by_id ? "" : "text-red-600"}>{row.decided_by_personal_number}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.decision_note ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.decision_note ?? ""}
                            onBlur={(e) => setFieldOverride("range_excusal_requests", row.row, "decision_note", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "soldier_personal_number", label: "מ\"א חייל", value: row.soldier_personal_number },
                                { key: "resolved_soldier_id", label: "מזהה חייל", value: row.resolved_soldier_id },
                                { key: "requested_by_personal_number", label: "מ\"א מבקש", value: row.requested_by_personal_number },
                                { key: "hierarchy_node_name", label: "יחידה", value: row.hierarchy_node_name },
                                { key: "range_type", label: "סוג מטווח", value: row.range_type },
                                { key: "date", label: "תאריך", value: row.date },
                                { key: "range_location_name", label: "מיקום", value: row.range_location_name },
                                { key: "resolved_range_event_id", label: "מזהה מטווח", value: row.resolved_range_event_id },
                                { key: "resolved_range_assignment_id", label: "מזהה שיבוץ", value: row.resolved_range_assignment_id },
                                { key: "reason", label: "סיבה", value: row.reason, editable: { type: "text", onChange: (v) => setFieldOverride("range_excusal_requests", row.row, "reason", v) } },
                                { key: "status", label: "סטטוס אישור", value: row.status },
                                { key: "decided_by_personal_number", label: "מ\"א מחליט", value: row.decided_by_personal_number },
                                { key: "decision_note", label: "הערת החלטה", value: row.decision_note, editable: { type: "text", onChange: (v) => setFieldOverride("range_excusal_requests", row.row, "decision_note", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("range_excusal_requests", row)}
                              onChange={(e) => setRowAction("range_excusal_requests", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- ImportSessionReviewPage`
Expected: PASS (full file — all tabs, all prior tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add range_excusal_requests tab content"
```

---

### Task 8: `ExportPage.tsx` — add range sheet checkboxes

**Files:**
- Modify: `frontend/src/pages/planning/ExportPage.tsx`
- Modify: `frontend/src/pages/planning/ExportPage.test.tsx`

**Interfaces:**
- Produces: 3 new checkboxes ("מיקומי מטווח" under config sheets, "מטווחים"/"שיבוצי מטווח" under data sheets); `handleExport` includes them in the `/config/export`/`/import/export` requests exactly like the existing config/data sheets.

- [ ] **Step 1: Write the failing tests**

Add to `ExportPage.test.tsx`, inside the `describe("ExportPage", ...)` block:

```typescript
  it("renders checkboxes for the new range sheets", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    expect(screen.getByLabelText(/מיקומי מטווח/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^מטווחים$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/שיבוצי מטווח/)).toBeInTheDocument();
  });

  it("calls /config/export with range_locations when checked", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    fireEvent.click(screen.getByLabelText(/מיקומי מטווח/));
    fireEvent.click(screen.getByText("ייצוא"));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/config/export?sheets=range_locations"),
        expect.anything(),
      );
    });
  });

  it("calls /import/export with range_events and range_assignments when checked", async () => {
    const importWb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(importWb, XLSX.utils.aoa_to_sheet([["hierarchy_node_name"], ["מדור א"]]), "range_events");
    const importBuf = XLSX.write(importWb, { type: "array", bookType: "xlsx" });
    const fetchMock = vi.fn().mockResolvedValue({ arrayBuffer: () => Promise.resolve(importBuf) });
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<ExportPage />);
    fireEvent.click(await screen.findByLabelText(/^מטווחים$/));
    fireEvent.click(await screen.findByLabelText(/שיבוצי מטווח/));
    fireEvent.click(screen.getByText("ייצוא"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/import/export?sheets=range_events,range_assignments",
        expect.objectContaining({ headers: expect.any(Object) }),
      );
    });
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- planning/ExportPage -t "range"`
Expected: FAIL

- [ ] **Step 3: Add the checkbox options**

In `ExportPage.tsx`, add to `CONFIG_SHEET_OPTIONS`:

```typescript
  { key: "range_locations", label: "מיקומי מטווח" },
```

Add to `DATA_SHEET_OPTIONS`:

```typescript
  { key: "range_events", label: "מטווחים" },
  { key: "range_assignments", label: "שיבוצי מטווח" },
```

No other changes are needed — `ALL_KEYS`, the render loop, and `handleExport`'s `configSheets`/`dataSheets` filters already derive from these two option arrays generically.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- planning/ExportPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/planning/ExportPage.tsx frontend/src/pages/planning/ExportPage.test.tsx
git commit -m "feat: add range sheets to export page"
```

---

### Task 9: `RangesPage.tsx` and `ImportUploadPage.tsx` — entry-point links

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`
- Modify: `frontend/src/pages/ImportUploadPage.tsx`

**Interfaces:**
- Produces: `RangesPage` renders "ייצוא"/"ייבוא" links (visible only when `manage` is true, matching the existing "מטווח חדש" button's gating) pointing at `/planning/export` and `/import`. `ImportUploadPage`'s sheet-name hint text mentions the range sheets.

- [ ] **Step 1: Write the failing test**

Read the top of `RangesPage.test.tsx` first to match its render/auth-mocking convention (it wraps the page in `MemoryRouter` and presumably mocks `useAuth`/`canPlan` to control the `manage` flag — match whatever it already does for the existing `"מטווח חדש"` button test). Add:

```typescript
  it("shows export/import links for a manager", async () => {
    renderPage(); // adjust to this file's existing render-with-manager helper
    await screen.findByTestId("ranges-page");
    expect(screen.getByRole("link", { name: "ייצוא" })).toHaveAttribute("href", "/planning/export");
    expect(screen.getByRole("link", { name: "ייבוא" })).toHaveAttribute("href", "/import");
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RangesPage -t "export/import links"`
Expected: FAIL (links don't exist)

- [ ] **Step 3: Add the links**

In `RangesPage.tsx`, add `Link` to the `react-router-dom` import: `import { Link, useSearchParams } from "react-router-dom";`.

Change the header line (the `<div className="flex flex-wrap justify-between items-center gap-2">...</div>` line) so the right-hand button group also includes the two links when `manage` is true:

```tsx
    <div className="flex flex-wrap justify-between items-center gap-2"><h1 className="text-xl font-semibold">מטווחים</h1><div className="flex items-center gap-3">{manage && <><Link to="/planning/export" className="text-indigo-600 hover:underline text-sm">ייצוא</Link><Link to="/import" className="text-indigo-600 hover:underline text-sm">ייבוא</Link></>}{!showIneligible && manage && <button type="button" data-testid="create-event-button" onClick={() => setFormEvent(null)} className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">מטווח חדש</button>}</div></div>
```

(This replaces the existing single-line header `<div>` — keep everything else on that line identical, only wrapping the existing `{!showIneligible && manage && <button ...>}` block together with the two new links inside a new `<div className="flex items-center gap-3">`.)

In `ImportUploadPage.tsx`, update the hint paragraph's sheet-name list to mention the range sheets:

```tsx
            העלה קובץ Excel עם גיליונות:{" "}
            <code>soldiers</code>, <code>duty_shifts</code>, <code>assignments</code>,{" "}
            <code>range_locations</code>, <code>range_events</code>, <code>range_assignments</code>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RangesPage`
Expected: PASS

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run: `cd frontend && npm run typecheck && npm test`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/pages/RangesPage.test.tsx frontend/src/pages/ImportUploadPage.tsx
git commit -m "feat: add export/import entry points to ranges and import upload pages"
```

---

## Self-Review Notes

- **Spec coverage:** all 5 sheets get review-page tabs (Tasks 3–7); `ExportPage.tsx` covers `range_locations`/`range_events`/`range_assignments` (Task 8) — `soldier_range_qualifications`/`range_excusal_requests` need no frontend export change since `/approvals/export` already exports unconditionally; discoverability links added (Task 9).
- **Type consistency:** every tab's `row.<field>` accesses match the interfaces defined in Task 1 exactly (e.g. `resolved_range_event_id`/`matched_session_row` used identically in Task 5's `range_assignments` tab and in Task 1's `RangeAssignmentImportRow`).
- **Scoping decision carried through consistently:** no tab in this plan adds a Combobox/`handlePick` picker for unresolved `hierarchy_node_name`/`range_location_name` — all such fields render as plain (red-on-error) text, per the Global Constraints note.
- **Depends on the backend plan:** these tests assume the `parsed_state`/`row_summary` shapes the backend plan produces; if backend field names diverge during implementation, this plan's row fixtures must be updated to match before these tests can pass against a real backend (they pass in isolation today because the frontend tests mock `getSession` directly).
