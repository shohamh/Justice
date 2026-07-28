# Swap Approval Card Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the misleading "not required" text on the swap approval cards, expose the missing duty-manager-approval setting, label the reason text, and redesign the requester/candidate approval status into a clearer bulleted, colored, two-(or-N-)column layout.

**Architecture:** A new presentational component `SwapApprovalColumns` owns the column layout, per-column bullet list, and per-column aggregate color/icon. `DirectCommanderApproval` gains an `approverKind` prop so its empty-state text can differ between "no commander required" and "no duty manager assigned to this scope." `SwapsPage.tsx` and `ApprovalsPage.tsx` are updated to build column data from the existing `SwapRequest`/`SwapCandidate` shapes and pass it to `SwapApprovalColumns`, without touching the existing interactive approve/reject controls (which stay exactly where they are today, same DOM order, so existing tests asserting button counts/order keep passing). `SystemSettingsPage.tsx` gets one new row for the already-enforced-but-unexposed `swaps.require_duty_manager_approval` setting.

**Tech Stack:** React + TypeScript, Tailwind CSS, react-i18next, Vitest + @testing-library/react.

## Global Constraints

- Frontend-only changes; no backend/API changes (the setting and its default already work server-side).
- New i18n strings go in `frontend/src/i18n/he.json` under the existing `swaps` namespace.
- Reuse `swaps.reason` ("סיבה"), `swaps.requester_approval` ("אישור מבקש"), `swaps.covering_approval` ("אישור מכסה"), `swaps.approver_kind_commander` ("מפקד"), `swaps.approver_kind_duty_manager` ("אחראי תורנויות") — do not add duplicate keys for these.
- New empty-state string for an unscoped duty manager: `swaps.no_duty_manager_assigned` = **"אין אחראי תורנויות משויך למסגרת"**.
- Column aggregate color rule: green+✓ only if every applicable requirement in that column is approved; red+✗ if anything in that column was rejected; amber+⋯ otherwise (still pending); no color/icon if nothing is applicable to that column at all.
- "My side" (when the viewer has one) is always the right-hand column, per RTL reading order.
- Do not change any existing approve/reject button's DOM position, text, or click handler — only the read-only status/label rendering around them changes.

---

### Task 1: Expose the duty-manager-approval setting

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx:45` (insert new row after the existing `swaps.require_manager_approval` entry)

**Interfaces:**
- Consumes: existing `SettingDef` interface (already defined in this file).
- Produces: nothing consumed by later tasks — this is a standalone, low-risk addition.

- [ ] **Step 1: Add the setting row**

In `frontend/src/pages/SystemSettingsPage.tsx`, change:

```tsx
  {
    label: "החלפות",
    settings: [
      { key: "swaps.require_manager_approval", label: "דורש אישור מפקד", description: "האם החלפות דורשות אישור מפקד", type: "boolean", defaultValue: true },
      {
        key: "swaps.restrict_to_hierarchy_level",
```

to:

```tsx
  {
    label: "החלפות",
    settings: [
      { key: "swaps.require_manager_approval", label: "דורש אישור מפקד", description: "האם החלפות דורשות אישור מפקד", type: "boolean", defaultValue: true },
      { key: "swaps.require_duty_manager_approval", label: "דורש אישור אחראי תורנויות", description: "האם החלפות דורשות אישור אחראי תורנויות (בנוסף לאישור מפקד)", type: "boolean", defaultValue: true },
      {
        key: "swaps.restrict_to_hierarchy_level",
```

- [ ] **Step 2: Run the existing settings test suite to confirm nothing broke**

Run: `npm test -- SystemSettingsPage --run` (from `frontend/`)
Expected: PASS (existing tests don't enumerate every row, so this addition doesn't affect them)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: expose swaps.require_duty_manager_approval in system settings"
```

---

### Task 2: Kind-aware empty-state text in DirectCommanderApproval

**Files:**
- Modify: `frontend/src/components/DirectCommanderApproval.tsx`
- Create: `frontend/src/components/DirectCommanderApproval.test.tsx`
- Modify: `frontend/src/i18n/he.json:849` (add new key next to `no_managers_required`)

**Interfaces:**
- Produces: `DirectCommanderApproval` now accepts an optional `approverKind?: "commander" | "duty_manager"` prop (defaults to `"commander"` so every existing call site — constraints/exemptions/field-updates/enrollment tabs in `ApprovalsPage.tsx`, none of which currently hit the empty branch — keeps behaving exactly as before).

- [ ] **Step 1: Add the new i18n key**

In `frontend/src/i18n/he.json`, next to line 849, change:

```json
    "no_managers_required": "לא נדרש אישור מפקד",
```

to:

```json
    "no_managers_required": "לא נדרש אישור מפקד",
    "no_duty_manager_assigned": "אין אחראי תורנויות משויך למסגרת",
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/DirectCommanderApproval.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import "../i18n";
import DirectCommanderApproval from "./DirectCommanderApproval";

describe("DirectCommanderApproval empty state", () => {
  test("shows the commander-flavored text when no commander chain exists", () => {
    render(<DirectCommanderApproval approvals={[]} approverKind="commander" />);
    expect(screen.getByText("לא נדרש אישור מפקד")).toBeInTheDocument();
  });

  test("shows a distinct duty-manager-flavored text when no duty manager is scoped", () => {
    render(<DirectCommanderApproval approvals={[]} approverKind="duty_manager" />);
    expect(screen.getByText("אין אחראי תורנויות משויך למסגרת")).toBeInTheDocument();
    expect(screen.queryByText("לא נדרש אישור מפקד")).not.toBeInTheDocument();
  });

  test("defaults to the commander-flavored text when approverKind is omitted", () => {
    render(<DirectCommanderApproval approvals={[]} />);
    expect(screen.getByText("לא נדרש אישור מפקד")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npm test -- DirectCommanderApproval --run` (from `frontend/`)
Expected: FAIL — the "duty-manager-flavored text" test fails because the component always renders `swaps.no_managers_required` regardless of kind.

- [ ] **Step 4: Implement the prop**

In `frontend/src/components/DirectCommanderApproval.tsx`, change:

```tsx
export default function DirectCommanderApproval({
  approvals,
}: {
  approvals: DirectCommanderApprovalRow[];
}) {
  const { t } = useTranslation();
  if (approvals.length === 0) {
    return <span className="text-gray-400">{t("swaps.no_managers_required")}</span>;
  }
```

to:

```tsx
export default function DirectCommanderApproval({
  approvals,
  approverKind = "commander",
}: {
  approvals: DirectCommanderApprovalRow[];
  approverKind?: "commander" | "duty_manager";
}) {
  const { t } = useTranslation();
  if (approvals.length === 0) {
    const emptyKey = approverKind === "duty_manager" ? "swaps.no_duty_manager_assigned" : "swaps.no_managers_required";
    return <span className="text-gray-400">{t(emptyKey)}</span>;
  }
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- DirectCommanderApproval --run` (from `frontend/`)
Expected: PASS (all 3 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DirectCommanderApproval.tsx frontend/src/components/DirectCommanderApproval.test.tsx frontend/src/i18n/he.json
git commit -m "fix: distinguish 'no duty manager assigned' from 'commander approval not required'"
```

---

### Task 3: Label the reason text

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:333,392,440`
- Modify: `frontend/src/pages/SwapsPage.test.tsx` (add one assertion)

**Interfaces:**
- Consumes: existing `swaps.reason` i18n key ("סיבה").

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/SwapsPage.test.tsx`, add a `reason` value to the existing `mySwap` fixture and a new test:

```tsx
// change the fixture's reason from `null` to a real value:
    reason: "אירוע משפחתי",
```

```tsx
describe("SwapsPage reason label", () => {
  test("prefixes the swap reason with a label instead of showing bare text", async () => {
    renderPage();
    expect(await screen.findByText("swaps.reason: אירוע משפחתי")).toBeInTheDocument();
  });
});
```

(The `react-i18next` mock in this file returns the key itself for `t(k)`, so the label renders literally as `swaps.reason`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- SwapsPage --run` (from `frontend/`)
Expected: FAIL — current markup renders `אירוע משפחתי` alone, without the `swaps.reason:` prefix.

- [ ] **Step 3: Add the label at all three call sites**

In `frontend/src/pages/SwapsPage.tsx`, change each of the three occurrences:

Line ~333 (`renderMySwapCard`):
```tsx
      {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
```
to:
```tsx
      {swap.reason && <p className="text-gray-500 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
```

Line ~392 (`renderBoardCard`):
```tsx
        {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
```
to:
```tsx
        {swap.reason && <p className="text-gray-500 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
```

Line ~440 (`renderIncomingCard`):
```tsx
        {swap.reason && <p className="text-gray-600 dark:text-gray-400 text-xs">{swap.reason}</p>}
```
to:
```tsx
        {swap.reason && <p className="text-gray-600 dark:text-gray-400 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- SwapsPage --run` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/pages/SwapsPage.test.tsx
git commit -m "fix: label the swap reason text instead of showing it bare"
```

---

### Task 4: New `SwapApprovalColumns` shared component

**Files:**
- Create: `frontend/src/components/SwapApprovalColumns.tsx`
- Create: `frontend/src/components/SwapApprovalColumns.test.tsx`

**Interfaces:**
- Consumes: `DirectCommanderApprovalRow` and `DirectCommanderApproval` (with the `approverKind` prop from Task 2).
- Produces (for Tasks 5 & 6 to use):
  ```ts
  export interface SwapApprovalColumn {
    label: string;
    soldierApprovalLabel?: string;   // e.g. t("swaps.requester_approval") or t("swaps.covering_approval") — omit to hide the soldier bullet entirely
    soldierApproved?: boolean | null; // undefined = no soldier-side bullet for this column
    commanderApprovals: DirectCommanderApprovalRow[];
    dutyManagerApprovals: DirectCommanderApprovalRow[];
    showDutyManagerRow: boolean;      // config toggle gate — false hides the duty-manager bullet entirely
  }
  export type ColumnStatus = "approved" | "rejected" | "pending" | "neutral";
  export function computeColumnStatus(column: SwapApprovalColumn): ColumnStatus;
  export default function SwapApprovalColumns({ columns }: { columns: SwapApprovalColumn[] }): JSX.Element;
  ```

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/SwapApprovalColumns.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import "../i18n";
import SwapApprovalColumns, { computeColumnStatus, SwapApprovalColumn } from "./SwapApprovalColumns";

function baseColumn(overrides: Partial<SwapApprovalColumn>): SwapApprovalColumn {
  return {
    label: "עמודה",
    commanderApprovals: [],
    dutyManagerApprovals: [],
    showDutyManagerRow: false,
    ...overrides,
  };
}

describe("computeColumnStatus", () => {
  test("neutral when nothing is applicable", () => {
    expect(computeColumnStatus(baseColumn({}))).toBe("neutral");
  });

  test("pending when soldier hasn't decided yet", () => {
    expect(computeColumnStatus(baseColumn({ soldierApproved: null }))).toBe("pending");
  });

  test("approved only when every applicable requirement is approved", () => {
    const column = baseColumn({
      soldierApproved: true,
      commanderApprovals: [{ commander_id: "c1", approved: true, approver_kind: "commander" }],
      dutyManagerApprovals: [{ commander_id: "d1", approved: false, approver_kind: "duty_manager" }],
      showDutyManagerRow: true,
    });
    // duty manager not yet approved -> whole column still pending, not approved
    expect(computeColumnStatus(column)).toBe("pending");
  });

  test("approved when soldier and all present chains are satisfied", () => {
    const column = baseColumn({
      soldierApproved: true,
      commanderApprovals: [{ commander_id: "c1", approved: true, approver_kind: "commander" }],
    });
    expect(computeColumnStatus(column)).toBe("approved");
  });

  test("rejected if any requirement was rejected, even if others are approved", () => {
    const column = baseColumn({
      soldierApproved: true,
      commanderApprovals: [{ commander_id: "c1", approved: false, rejected: true, approver_kind: "commander" }],
    });
    expect(computeColumnStatus(column)).toBe("rejected");
  });
});

describe("SwapApprovalColumns rendering", () => {
  test("renders one bullet per applicable line, labeled and separated by column", () => {
    render(
      <SwapApprovalColumns
        columns={[
          baseColumn({
            label: "אני",
            soldierApprovalLabel: "אישור מכסה",
            soldierApproved: true,
            commanderApprovals: [{ commander_id: "c1", commander_name: "רשצ מארס", approved: false, approver_kind: "commander" }],
          }),
          baseColumn({
            label: "מבקש",
            soldierApprovalLabel: "אישור מבקש",
            soldierApproved: null,
            showDutyManagerRow: true,
            dutyManagerApprovals: [],
          }),
        ]}
      />
    );
    expect(screen.getByText("אני")).toBeInTheDocument();
    expect(screen.getByText("מבקש")).toBeInTheDocument();
    expect(screen.getByText("אישור מכסה")).toBeInTheDocument();
    expect(screen.getByText("אישור מבקש")).toBeInTheDocument();
    expect(screen.getByText("אין אחראי תורנויות משויך למסגרת")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- SwapApprovalColumns --run` (from `frontend/`)
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/SwapApprovalColumns.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import DirectCommanderApproval, { DirectCommanderApprovalRow, isSideSatisfied } from "./DirectCommanderApproval";

export interface SwapApprovalColumn {
  label: string;
  soldierApprovalLabel?: string;
  soldierApproved?: boolean | null;
  commanderApprovals: DirectCommanderApprovalRow[];
  dutyManagerApprovals: DirectCommanderApprovalRow[];
  showDutyManagerRow: boolean;
}

export type ColumnStatus = "approved" | "rejected" | "pending" | "neutral";
type ReqStatus = "approved" | "rejected" | "pending" | "none";

function soldierReqStatus(value?: boolean | null): ReqStatus {
  if (value === undefined) return "none";
  if (value === true) return "approved";
  if (value === false) return "rejected";
  return "pending";
}

function chainReqStatus(rows: DirectCommanderApprovalRow[]): ReqStatus {
  if (rows.length === 0) return "none";
  if (rows.some((r) => r.rejected)) return "rejected";
  if (isSideSatisfied(rows)) return "approved";
  return "pending";
}

export function computeColumnStatus(column: SwapApprovalColumn): ColumnStatus {
  const statuses: ReqStatus[] = [
    soldierReqStatus(column.soldierApproved),
    chainReqStatus(column.commanderApprovals),
    column.showDutyManagerRow ? chainReqStatus(column.dutyManagerApprovals) : "none",
  ];
  if (statuses.some((s) => s === "rejected")) return "rejected";
  if (statuses.every((s) => s === "none")) return "neutral";
  if (statuses.some((s) => s === "pending")) return "pending";
  return "approved";
}

const STATUS_STYLES: Record<ColumnStatus, { bg: string; text: string; icon: string }> = {
  approved: { bg: "bg-green-50 dark:bg-green-950/40", text: "text-green-700 dark:text-green-300", icon: "✓" },
  rejected: { bg: "bg-red-50 dark:bg-red-950/40", text: "text-red-600 dark:text-red-300", icon: "✗" },
  pending: { bg: "bg-amber-50 dark:bg-amber-950/40", text: "text-amber-700 dark:text-amber-300", icon: "⋯" },
  neutral: { bg: "", text: "text-gray-500 dark:text-gray-400", icon: "" },
};

function SoldierApprovalDot({ value }: { value: boolean | null }) {
  if (value === true) return <span className="text-green-600 font-bold">✓</span>;
  if (value === false) return <span className="text-red-500 font-bold">✗</span>;
  return <span className="text-gray-400">—</span>;
}

export default function SwapApprovalColumns({ columns }: { columns: SwapApprovalColumn[] }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex divide-x divide-x-reverse dark:divide-gray-600 border rounded dark:border-gray-600 overflow-hidden text-xs"
      dir="rtl"
    >
      {columns.map((column, i) => {
        const status = computeColumnStatus(column);
        const style = STATUS_STYLES[status];
        return (
          <div key={i} className={`flex-1 min-w-[130px] p-2 space-y-1 ${style.bg}`}>
            <div className={`flex items-center justify-between font-medium ${style.text}`}>
              <span>{column.label}</span>
              {style.icon && <span>{style.icon}</span>}
            </div>
            <ul className="space-y-0.5 list-disc list-inside text-gray-600 dark:text-gray-300">
              {column.soldierApproved !== undefined && column.soldierApprovalLabel && (
                <li>
                  {column.soldierApprovalLabel}: <SoldierApprovalDot value={column.soldierApproved ?? null} />
                </li>
              )}
              {column.commanderApprovals.length > 0 && (
                <li>
                  {t("swaps.approver_kind_commander")}:{" "}
                  <DirectCommanderApproval approvals={column.commanderApprovals} approverKind="commander" />
                </li>
              )}
              {column.showDutyManagerRow && (
                <li>
                  {t("swaps.approver_kind_duty_manager")}:{" "}
                  <DirectCommanderApproval approvals={column.dutyManagerApprovals} approverKind="duty_manager" />
                </li>
              )}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
```

Also export `isSideSatisfied` from `DirectCommanderApproval.tsx` if not already exported (it already is, per the existing file — no change needed there).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- SwapApprovalColumns --run` (from `frontend/`)
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SwapApprovalColumns.tsx frontend/src/components/SwapApprovalColumns.test.tsx
git commit -m "feat: add SwapApprovalColumns shared two-column approval status component"
```

---

### Task 5: Wire `SwapApprovalColumns` into `SwapsPage.tsx`

**Correction (found during implementation):** the code below has two bugs that surface as test failures — fix them as part of this task, not as a separate pass:

1. **Name duplication.** Both the new columns (labeled with each live candidate's name) and the unchanged `CandidateRow` (which also prints the candidate's name) render for the same "live" candidates, so names like "Yossi"/"Dana" appear twice in the DOM and break `findByText`. Fix: `CandidateRow` only prints the candidate's name when the candidate is NOT live (i.e. `status` is `"declined"`, `"cancelled"`, or `"applied"`) — live candidates' names already come from the column label. Give `CandidateRow` a `showName: boolean` prop; callers pass `showName={candidate.status !== "pending" && candidate.status !== "accepted"}`.
2. **Requester column shows no name.** `requesterColumn(...)` is called with the literal label `t("swaps.requester")` in `renderIncomingCard` and `PendingApprovalCard`, so the requester's actual name never appears anywhere — inconsistent with candidate columns, which do show real names. Fix: in those two call sites (NOT in `renderMySwapCard`, where the viewer IS the requester and `t("swaps.mine")` is correct as-is), pass `swap.requesting_soldier_name ?? t("swaps.requester")` as the label instead of the bare `t("swaps.requester")`.

The code blocks below have NOT been re-edited to show these two fixes inline — apply them on top of the code as written.

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx` (functions `ApprovalStatus`, `CandidateRow`, `PendingApprovalCard`, `renderIncomingCard`, `renderMySwapCard`)
- Modify: `frontend/src/pages/SwapsPage.test.tsx`

**Interfaces:**
- Consumes: `SwapApprovalColumns`, `SwapApprovalColumn` from Task 4; `groupByKind` (existing, from `DirectCommanderApproval.tsx`).

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/SwapsPage.test.tsx`, add a case that renders the incoming tab and asserts the column block appears above the reason text, with "my side" (the viewing candidate, "me") on the right. Add this describe block:

```tsx
describe("SwapsPage incoming tab approval columns", () => {
  test("shows a two-column approval block for an incoming swap, mine first", async () => {
    const { getSwapConfig, listIncomingSwaps } = await import("../api/swaps");
    vi.mocked(listIncomingSwaps).mockResolvedValueOnce([
      {
        id: "req2", duty_assignment_id: "a2", duty_date: "2026-08-05", requesting_soldier_id: "other",
        open_to_marketplace: true, status: "open", reason: null, requester_side_approved: null,
        decision_note: null, created_at: "2026-07-01T00:00:00Z",
        duty_type_name: "Patrol", duty_location_name: "North", duty_type_id: "dt2", duty_location_id: "l2",
        duty_start_date: "2026-08-05", duty_end_date: "2026-08-06", duty_shift_id: null,
        requesting_soldier_name: "Other", requesting_commander_name: null, requesting_soldier_node_name: null,
        requester_manager_approvals: [],
        candidates: [
          { id: "c3", soldier_id: "me", soldier_name: "Me", source: "invited", status: "pending", soldier_side_approved: null, offered_assignment_ids: [], manager_approvals: [] },
        ],
      },
    ]);
    vi.mocked(getSwapConfig).mockResolvedValueOnce({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/swaps?tab=incoming"]}>
          <SwapsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const meLabel = await screen.findByText("swaps.covering");
    const requesterLabel = screen.getByText("Other");
    // "Me" column must come before the requester column in DOM order (right-first in RTL).
    expect(meLabel.compareDocumentPosition(requesterLabel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
```

Note: this test imports `render`/`screen`/`QueryClient`/`QueryClientProvider`/`MemoryRouter` which are already imported at the top of this file — no new imports needed.

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- SwapsPage --run` (from `frontend/`)
Expected: FAIL — current `renderIncomingCard` never renders a "me" column at all (only the requester's approval status is shown today).

- [ ] **Step 3: Implement — replace `ApprovalStatus` and update `CandidateRow`/`PendingApprovalCard`/`renderIncomingCard`/`renderMySwapCard`**

In `frontend/src/pages/SwapsPage.tsx`, add the import:

```tsx
import SwapApprovalColumns, { SwapApprovalColumn } from "../components/SwapApprovalColumns";
```

Replace the `ApprovalStatus` function (lines ~121-143) with column-builder helpers. Each already-existing call site has a `t` function in scope (either a `t` prop or `useTranslation()`), so these take `t` as a parameter rather than importing a second i18n instance:

```tsx
function requesterColumn(
  swap: SwapRequest, requireDutyManagerApproval: boolean, label: string, t: (k: string) => string,
): SwapApprovalColumn {
  const groups = groupByKind(swap.requester_manager_approvals);
  return {
    label,
    soldierApprovalLabel: t("swaps.requester_approval"),
    soldierApproved: swap.requester_side_approved,
    commanderApprovals: groups.commander,
    dutyManagerApprovals: groups.duty_manager,
    showDutyManagerRow: requireDutyManagerApproval,
  };
}

function candidateColumn(
  candidate: SwapRequest["candidates"][number], requireDutyManagerApproval: boolean, label: string, t: (k: string) => string,
): SwapApprovalColumn {
  const groups = groupByKind(candidate.manager_approvals);
  return {
    label,
    soldierApprovalLabel: t("swaps.covering_approval"),
    soldierApproved: candidate.soldier_side_approved,
    commanderApprovals: groups.commander,
    dutyManagerApprovals: groups.duty_manager,
    showDutyManagerRow: requireDutyManagerApproval,
  };
}
```

Now update `CandidateRow` (lines ~145-172) to drop its own manual approval rendering and instead expose the raw data needed by callers — simplest: keep `CandidateRow` only for the "mine"/"pending" tabs' per-candidate summary (source/status badges), and move approval-column rendering to the call sites that already have both the requester and the candidate:

```tsx
function CandidateRow({ candidate, t }: {
  candidate: SwapRequest["candidates"][number];
  t: (k: string) => string;
}) {
  const sourceLabel = candidate.source === "marketplace" ? t("swaps.candidate_source_marketplace") : t("swaps.candidate_source_invited");
  return (
    <div className="border rounded p-2 text-xs space-y-1 dark:border-gray-600">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium dark:text-gray-100">{candidate.soldier_name ?? candidate.soldier_id.slice(0, 8)}</span>
        <span className="text-gray-400">{sourceLabel}</span>
      </div>
      {candidate.status === "declined" && <p className="text-red-500">{t("swaps.candidate_declined")}</p>}
      {candidate.status === "cancelled" && <p className="text-gray-400">{t("swaps.candidate_cancelled")}</p>}
      {candidate.status === "applied" && <p className="text-green-600">{t("swaps.candidate_applied")}</p>}
    </div>
  );
}
```

Update `PendingApprovalCard` (lines ~63-87) to render the column block above the flex row of `CandidateRow`s:

```tsx
function PendingApprovalCard({
  swap, requireManagerApproval, requireDutyManagerApproval, onShiftClick, t,
}: {
  swap: SwapRequest; requireManagerApproval: boolean; requireDutyManagerApproval: boolean;
  onShiftClick?: () => void; t: (k: string) => string;
}) {
  const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
  const columns: SwapApprovalColumn[] = requireManagerApproval
    ? [
        requesterColumn(swap, requireDutyManagerApproval, t("swaps.requester"), t),
        ...liveCandidates.map((c) => candidateColumn(c, requireDutyManagerApproval, c.soldier_name ?? c.soldier_id.slice(0, 8), t)),
      ]
    : [];
  return (
    <li className="border rounded-lg p-4 space-y-3 dark:border-gray-600">
      <SwapDutyHeader swap={swap} onShiftClick={onShiftClick} />
      {columns.length > 0 && <SwapApprovalColumns columns={columns} />}
      <div className="flex flex-wrap gap-3">
        {liveCandidates.map((c) => (
          <div key={c.id} className="flex-1 min-w-[140px]">
            <CandidateRow candidate={c} t={t} />
          </div>
        ))}
      </div>
    </li>
  );
}
```

Update `renderMySwapCard` (the block around lines ~325-371): insert the columns block right after `SwapDutyHeader`, before the status badge row's sibling content, and drop the now-unused `requireManagerApproval`/`requireDutyManagerApproval` args from the `CandidateRow` calls at line ~360:

```tsx
  const renderMySwapCard = (swap: SwapRequest) => {
    const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
    const columns: SwapApprovalColumn[] = requireManagerApproval && liveCandidates.length > 0
      ? [
          requesterColumn(swap, requireDutyManagerApproval, t("swaps.mine"), t),
          ...liveCandidates.map((c) => candidateColumn(c, requireDutyManagerApproval, c.soldier_name ?? c.soldier_id.slice(0, 8), t)),
        ]
      : [];
    return (
    <li key={swap.id} className="border rounded p-3 text-sm space-y-1.5 dark:border-gray-600">
      <div className="flex items-start justify-between gap-2">
        <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
        <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
          {t(statusKey(swap.status))}
        </span>
      </div>
      {columns.length > 0 && <SwapApprovalColumns columns={columns} />}
      {swap.reason && <p className="text-gray-500 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
      {swap.decision_note && (
        <p className="text-xs text-amber-600 dark:text-amber-400">{t("swaps.decision_note")}: {swap.decision_note}</p>
      )}
      {swap.status === "open" && swap.requester_side_approved !== true && (
        <div className="flex gap-2 items-center">
          <button type="button" onClick={() => handleSoldierApprove(swap.id)}
            className="bg-green-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.approve")}
          </button>
          <input
            placeholder={t("approvals.decision_note")}
            value={swapRejectNote[swap.id] ?? ""}
            onChange={(e) => setSwapRejectNote((prev) => ({ ...prev, [swap.id]: e.target.value }))}
            className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
          <button type="button" onClick={() => handleSoldierReject(swap.id)}
            className="bg-red-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.reject")}
          </button>
        </div>
      )}
      {swap.candidates.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{t("swaps.candidates_title")} ({swap.candidates.length})</p>
          <div className="space-y-1">
            {swap.candidates.map((c) => (
              <CandidateRow key={c.id} candidate={c} t={t} />
            ))}
          </div>
        </div>
      )}
      {swap.status === "open" && (
        <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
          {t("swaps.cancel")}
        </button>
      )}
    </li>
    );
  };
```

Update `renderIncomingCard` (the block around lines ~408-452) to build a 2-column block with "me" (the viewing candidate) on the right and the requester on the left:

```tsx
  const renderIncomingCard = (swap: SwapRequest) => {
    const elig = coverEligibility[swap.duty_assignment_id];
    const coverDisabled = elig != null && !elig.eligible;
    const myCandidate = swap.candidates.find((c) => c.soldier_id === user?.id);
    const columns: SwapApprovalColumn[] = requireManagerApproval
      ? [
          ...(myCandidate ? [candidateColumn(myCandidate, requireDutyManagerApproval, t("swaps.covering"), t)] : []),
          requesterColumn(swap, requireDutyManagerApproval, t("swaps.requester"), t),
        ]
      : [];
    return (
      <li key={swap.id}
        className="border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 rounded p-3 text-sm space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
          <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
            {t(statusKey(swap.status))}
          </span>
        </div>
        {columns.length > 0 && <SwapApprovalColumns columns={columns} />}
        {myCandidate && myCandidate.status === "pending" && (
          <div className="flex gap-2 items-center">
            <button type="button" onClick={() => handleSoldierApprove(swap.id)}
              className="bg-green-600 text-white px-2 py-1 rounded text-xs">
              {t("approvals.approve")}
            </button>
            <input
              placeholder={t("approvals.decision_note")}
              value={swapRejectNote[swap.id] ?? ""}
              onChange={(e) => setSwapRejectNote((prev) => ({ ...prev, [swap.id]: e.target.value }))}
              className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
            <button type="button" onClick={() => handleSoldierReject(swap.id)}
              className="bg-red-600 text-white px-2 py-1 rounded text-xs">
              {t("approvals.reject")}
            </button>
          </div>
        )}
        {swap.reason && <p className="text-gray-600 dark:text-gray-400 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
        <button
          type="button"
          onClick={coverDisabled ? undefined : () => setCoverSwap(swap)}
          disabled={coverDisabled}
          title={coverDisabled ? (elig.reason ?? undefined) : undefined}
          className={`px-2 py-1 rounded text-xs ${coverDisabled ? "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed" : "bg-indigo-600 text-white hover:bg-indigo-700"}`}
        >
          {t("swaps.accept_cover")}
        </button>
      </li>
    );
  };
```

Remove the now-dead `ApprovalDot`/`ApprovalBadge` helper functions only if nothing else in the file still uses them — check first (grep for `<ApprovalDot` and `<ApprovalBadge` in the file after these edits; `ApprovalBadge` was used inside the old `PendingApprovalCard`'s requester block and `CandidateRow`, both now removed, so delete both helper functions if no remaining references).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- SwapsPage --run` (from `frontend/`)
Expected: PASS (all tests, including the pre-existing "one card per request" test and the new column-order test)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/pages/SwapsPage.test.tsx
git commit -m "feat: two-column bulleted approval status on swap cards"
```

---

### Task 6: Wire `SwapApprovalColumns` into `ApprovalsPage.tsx` swaps tab

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (swaps tab block, lines ~599-702)
- Modify: `frontend/src/pages/ApprovalsPage.test.tsx` (verify existing assertions still pass; no new test required since Task 4/5 already cover the column logic and this task only changes layout/labels around existing buttons)

**Interfaces:**
- Consumes: `SwapApprovalColumns`, `SwapApprovalColumn` from Task 4.

- [ ] **Step 1: Run the existing swaps-tab test first to capture the current passing baseline**

Run: `npm test -- ApprovalsPage --run` (from `frontend/`)
Expected: PASS (baseline, before this task's changes)

- [ ] **Step 2: Replace the read-only status portion, keep every button as-is**

In `frontend/src/pages/ApprovalsPage.tsx`, add the import:

```tsx
import SwapApprovalColumns, { SwapApprovalColumn } from "../components/SwapApprovalColumns";
```

Replace the swaps-tab body (lines ~599-702) — keep every `<button>`/`<input>` element exactly as-is (same order, same handlers, same text) so the existing "one approval block per live candidate" test (which counts/indexes buttons) keeps passing; only the surrounding status display changes from the old `SwapKindApproval`/`ApprovalDotInline`-based markup to `SwapApprovalColumns`:

```tsx
        {tab === "swaps" && (
          <div className="space-y-3" dir="rtl">
            {swapItems.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.none")}</p>}
            {swapItems.map(swap => {
              const isAdmin = user?.role === "admin";
              const reqGroups = groupByKind(swap.requester_manager_approvals);
              const liveCandidates = swap.candidates.filter(c => c.status === "pending" || c.status === "accepted");
              const statusColumns: SwapApprovalColumn[] = [
                {
                  label: `${t("swaps.requester")}: ${swap.requesting_soldier_name || swap.requesting_soldier_id.slice(0, 8)}`,
                  soldierApprovalLabel: t("swaps.requester_approval"),
                  soldierApproved: swap.requester_side_approved,
                  commanderApprovals: reqGroups.commander,
                  dutyManagerApprovals: reqGroups.duty_manager,
                  showDutyManagerRow: reqGroups.duty_manager.length > 0,
                },
                ...liveCandidates.map(candidate => {
                  const covGroups = groupByKind(candidate.manager_approvals);
                  return {
                    label: candidate.soldier_name || candidate.soldier_id.slice(0, 8),
                    soldierApprovalLabel: t("swaps.covering_approval"),
                    soldierApproved: candidate.soldier_side_approved,
                    commanderApprovals: covGroups.commander,
                    dutyManagerApprovals: covGroups.duty_manager,
                    showDutyManagerRow: covGroups.duty_manager.length > 0,
                  };
                }),
              ];
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
                  <SwapApprovalColumns columns={statusColumns} />
                  <div className="text-xs text-gray-500 space-y-1">
                    <SwapKindApproval
                      approvals={reqGroups.commander}
                      label={`${t("swaps.requester_managers")} (${t("swaps.approver_kind_commander")})`}
                      canAct={isAdmin || reqGroups.commander.some(a => a.commander_id === user?.id)}
                      onApprove={() => onSwapManagerApprove(swap.id, "requester")}
                      t={t}
                    />
                    <SwapKindApproval
                      approvals={reqGroups.duty_manager}
                      label={`${t("swaps.requester_managers")} (${t("swaps.approver_kind_duty_manager")})`}
                      canAct={isAdmin || !!user?.is_duty_manager}
                      onApprove={() => onSwapManagerApprove(swap.id, "requester")}
                      t={t}
                    />
                  </div>
                  <div className="flex gap-2 items-center flex-wrap">
                    <input
                      placeholder={t("approvals.decision_note")}
                      value={swapRejectNotes[swap.id] ?? ""}
                      onChange={e => setSwapRejectNotes(prev => ({ ...prev, [swap.id]: e.target.value }))}
                      className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    />
                    <button
                      onClick={() => onSwapManagerReject(swap.id)}
                      className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                  {liveCandidates.length > 0 && (
                    <div className="space-y-2 border-t pt-2 dark:border-gray-700">
                      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{t("swaps.candidates_title")} ({liveCandidates.length})</p>
                      {liveCandidates.map(candidate => {
                        const covGroups = groupByKind(candidate.manager_approvals);
                        return (
                          <div key={candidate.id} className="border rounded p-2 space-y-1">
                            <div className="flex items-center gap-2">
                              <SoldierLink id={candidate.soldier_id} name={candidate.soldier_name || candidate.soldier_id.slice(0, 8)} />
                            </div>
                            <div className="text-xs text-gray-500 space-y-1">
                              <SwapKindApproval
                                approvals={covGroups.commander}
                                label={`${t("swaps.covering_managers")} (${t("swaps.approver_kind_commander")})`}
                                canAct={isAdmin || covGroups.commander.some(a => a.commander_id === user?.id)}
                                onApprove={() => onSwapManagerApprove(swap.id, "covering", candidate.id)}
                                t={t}
                              />
                              <SwapKindApproval
                                approvals={covGroups.duty_manager}
                                label={`${t("swaps.covering_managers")} (${t("swaps.approver_kind_duty_manager")})`}
                                canAct={isAdmin || !!user?.is_duty_manager}
                                onApprove={() => onSwapManagerApprove(swap.id, "covering", candidate.id)}
                                t={t}
                              />
                            </div>
                            <div className="flex gap-2 items-center flex-wrap">
                              <input
                                placeholder={t("approvals.decision_note")}
                                value={swapRejectNotes[`${swap.id}:${candidate.id}`] ?? ""}
                                onChange={e => setSwapRejectNotes(prev => ({ ...prev, [`${swap.id}:${candidate.id}`]: e.target.value }))}
                                className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                              />
                              <button
                                onClick={() => onSwapManagerReject(swap.id, candidate.id)}
                                className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                              >
                                {t("approvals.reject")}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
```

Note this keeps `<ApprovalDotInline value={swap.requester_side_approved} />` removed from the header line (now redundant with the new column bullet) and drops the plain `<SoldierLink>`/duty-date-only header in favor of the label already carried inside `statusColumns[0].label` — but the candidate `<SoldierLink>` block under "candidates_title" is kept (it's what the existing test's `screen.findByText("Pending Candidate")` / `"Accepted Candidate"` locates, since those names also appear in the new columns' labels — verify in Step 3 below that this doesn't create duplicate-text ambiguity for `getByText`).

- [ ] **Step 3: Run the existing test and check for duplicate-text ambiguity**

Run: `npm test -- ApprovalsPage --run` (from `frontend/`)

If `screen.getByText("Accepted Candidate")` (or similar) now fails with "found multiple elements" because the name appears both in a `SwapApprovalColumns` column label and in the retained `<SoldierLink>` block: fix by removing the duplicate `<SoldierLink>` `div` immediately under `liveCandidates.map` (the `<div className="flex items-center gap-2"><SoldierLink .../></div>` right before `covGroups`) since the candidate's name is now already shown as that column's label in `SwapApprovalColumns`.

Expected after fix: PASS (existing "one approval block per live candidate" test's button-count/order assertions are unaffected — no button elements were removed or reordered, only the `SoldierLink`-only wrapper div was deleted since it duplicated the column label).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat: use SwapApprovalColumns for swap-tab status display in ApprovalsPage"
```

---

## Final verification

- [ ] **Run the full frontend test suite**

Run: `npm test --run` (from `frontend/`)
Expected: PASS

- [ ] **Run lint and typecheck**

Run: `npm run lint` then `npm run typecheck` (from `frontend/`)
Expected: no errors, no warnings
