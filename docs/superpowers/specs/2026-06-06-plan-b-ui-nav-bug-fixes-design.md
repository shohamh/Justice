# Plan B — UI / Nav Bug Fixes
**Date:** 2026-06-06  
**Issues:** #8, #10, #12, #21, #24

---

## Overview

Five independent bug fixes that improve visual correctness, navigation badge accuracy, broken functionality, and date formatting consistency across the app.

---

## 1. Commander nav badge — wrong count (#8)

**Current state:** `UnifiedNav` computes `pendingCount = constraints + exemptions + fieldUpdates`. It has a separate `swapIncomingCount` shown on the Swaps tab. Enrollment requests are fetched in `HomePage` but never reflected in the nav badge.

**Design:**
- Add `enrollmentCount` to the `pendingCount` calculation (fetch `listPendingEnrollments().length`).
- The badge on the מפקד tab shows `pendingCount + enrollmentCount` (all actionable items for a commander).
- `swapIncomingCount` stays on the Swaps tab badge (it's personal, not commander-specific).
- Single `useEffect` in `UnifiedNav` fetches all 4 counts in parallel when `canApprove`.

---

## 2. Hierarchy tree text color (#10)

**Current state:** `HierarchyTree` renders node names with `text-gray-700 dark:text-gray-300`. On pages with a dark sidebar or dark card background, `text-gray-700` (dark gray on dark background) is near-invisible.

**Design:**
- Change unselected node label class to `text-gray-900 dark:text-white`.
- Apply in both `HierarchyTree.tsx` and any inline tree renderers in `TransparencyPage.tsx` and `CommandDashboardPage.tsx`.
- Selected state remains `text-indigo-700 dark:text-indigo-300` (already readable).

---

## 3. Selectbox sorting by hierarchy + white-on-white fix (#12)

**Two sub-problems:**

**A — Hierarchy sort:** Any `<select>` or dropdown listing hierarchy nodes must order items by DFS traversal of the tree (same visual order as the tree widget). Affected components: `SubHierarchySelector`, the "העבר" (transfer) dialog, `AlgorithmRunForm` node picker, any others.
- Extract a `sortNodesByTree(nodes: NodeDTO[], tree: NodeDTO[]): NodeDTO[]` utility that performs DFS and returns nodes in tree order.
- Apply this utility wherever hierarchy nodes are listed in a select.

**B — White-on-white:** Native `<select>` elements inherit text color from the browser default in some themes. Fix all hierarchy `<select>` elements with explicit `text-gray-900 dark:text-white bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600` Tailwind classes.

---

## 4. Clear assignments buttons broken (#21)

**Current state:** "נקה שיבוצים" (clear assignments) per-duty and "נקה הכל" in `DutyManagementPage` do not work.

**Design:**
- Investigate root cause: likely a missing `await`, wrong HTTP method, or endpoint URL mismatch.
- The backend endpoint `DELETE /assignments/bulk` or similar should accept either a list of assignment IDs or a shift ID.
- Fix the frontend call to match the actual endpoint signature.
- Add a confirmation dialog before clearing (destructive operation).
- After clearing, refresh the shift list to reflect the change.

**Investigation needed:** Read `DutyManagementPage.tsx` and `backend/app/routes/assignments.py` to find the exact mismatch before implementing.

---

## 5. Datetime format — dd.mm.yyyy everywhere (#24)

**Current state:** Dates are displayed inconsistently — some use `toLocaleDateString("he-IL")` (which outputs `d/m/yyyy`), some use ISO format (`yyyy-mm-dd`), some use `en-US` locale.

**Design:**
- Add a shared utility `src/utils/formatDate.ts`:
  ```ts
  export function formatDate(d: string | Date): string {
    const date = typeof d === "string" ? new Date(d) : d;
    const dd = String(date.getDate()).padStart(2, "0");
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const yyyy = date.getFullYear();
    return `${dd}.${mm}.${yyyy}`;
  }
  
  export function formatDateRange(start: string | Date, end: string | Date): string {
    if (typeof start === "string" && typeof end === "string" && start === end)
      return formatDate(start);
    return `${formatDate(start)} – ${formatDate(end)}`;
  }
  ```
- Global search-and-replace: replace all `toLocaleDateString(...)` date display calls and ISO substring slices used for display (not for API calls) with `formatDate(...)`.
- ISO strings sent to the API are untouched — only display-facing code changes.
- Affects: `SwapStatusWidget`, `UpcomingDutiesWidget`, `DutyHistoryWidget`, `DutyManagementPage`, `TransparencyPage`, `AlgorithmProposalTable`, and others found during audit.

---

## Testing

- Nav badge on מפקד tab shows sum of all 4 pending categories.
- Hierarchy node names are readable on both light and dark backgrounds.
- Hierarchy select options are in tree DFS order; text is visible.
- "נקה שיבוצים" clears the correct assignments; confirmation dialog fires first.
- All dates throughout the app display as `dd.mm.yyyy`.
