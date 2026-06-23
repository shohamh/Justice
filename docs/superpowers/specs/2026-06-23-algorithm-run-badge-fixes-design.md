# Algorithm Run Badge Fixes — Design

**Goal:** Fix two issues with the algorithm-run badges introduced in [2026-06-23-algorithm-run-status-badges-design.md](2026-06-23-algorithm-run-status-badges-design.md):

1. A cancelled run (`status="failed"`, `error_message="cancelled_by_user"`) still counts toward the red "failed" badge, even though the user has already acted on it by cancelling.
2. The aggregate nav badge (`UnifiedNav.tsx` tab badge + `NavSheet.tsx` item badge) is always a hardcoded red pill, regardless of what mix of run statuses it represents.

## Root cause

Backend: `DELETE /algorithm/jobs/{id}` ([algorithm.py:619-633](../../../backend/app/routes/algorithm.py)) sets `job.status = "failed"` and `job.error_message = "cancelled_by_user"` when a pending/running job is cancelled. There is no separate `"cancelled"` status — cancellation is represented as a flavor of `"failed"`.

Frontend: both `ShiftsManagementPage.tsx`'s badge grouping and `UnifiedNav.tsx`'s badge count treat any `status === "failed"` job as needing attention, with no carve-out for the cancelled flavor.

(Publishing does **not** need a fix: `_maybe_publish_job` in `algorithm.py:188-203` already flips a job's status to `"published"` once all its draft proposals are resolved, which already falls outside all 4 badge groups — no frontend change needed there.)

## Shared util

New file: `frontend/src/utils/algorithmRunBadges.ts`

```ts
export interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

export function computeRunBadgeCounts(jobs: { status: string; mode: string; error_message: string | null }[]): RunBadgeCounts
```

Grouping rules (applied in this order — a cancelled job matches none of these and contributes to no bucket):
- Skip entirely if `status === "failed" && error_message === "cancelled_by_user"`.
- `running`: `status === "pending" || status === "running"`.
- `draft`: `status === "done" && mode === "shadow"`.
- `done`: `status === "done" && mode === "dm_reviewed"`.
- `failed`: `status === "failed"` (and not cancelled, per the skip above).

Both `ShiftsManagementPage.tsx` and `UnifiedNav.tsx` call this one function instead of each re-implementing the grouping logic, so the cancelled-job exclusion (and any future grouping fix) only needs to be made once.

## ShiftsManagementPage.tsx

Replace the inline `reduce` in the polling effect with `computeRunBadgeCounts(result.items)`. No visual changes — same 4 pills, same visibility rule (`count > 0`). `JobSummaryOut` already includes `error_message`, so no API/type change needed.

## UnifiedNav.tsx — color logic

Add a second derived value alongside the existing `algorithmBadgeCount`:　a priority-based color, computed from the same `computeRunBadgeCounts` result:

```ts
function pickBadgeColor(counts: RunBadgeCounts): "red" | "blue" | "yellow" | "green" {
  if (counts.failed > 0) return "red";
  if (counts.running > 0) return "blue";
  if (counts.draft > 0) return "yellow";
  return "green"; // counts.done > 0, or all zero (badge won't render anyway)
}
```

`algorithmBadgeCount` becomes the sum of all 4 buckets (`running + draft + done + failed`) computed via `computeRunBadgeCounts` — functionally identical to today's `result.items.length` except cancelled jobs no longer inflate it.

## NavTab / NavSheetItem — badgeColor prop

Both `NavTab` (in `UnifiedNav.tsx`) and `NavSheetItem` (in `NavSheet.tsx`) gain an optional field:

```ts
badgeColor?: "red" | "blue" | "yellow" | "green"; // defaults to "red"
```

All existing badge usages (`pendingCount`, `swapIncomingCount`, etc.) keep their current red appearance unchanged by simply not passing `badgeColor` (default applies). Only the two algorithm-run badge usages (`planningTab` and the `planning_shifts` entry in `planningItems`) pass the new computed color.

Color-to-class mapping (solid pill, matching the existing `bg-red-500 text-white` style):

| Color  | Classes                          |
|--------|-----------------------------------|
| red    | `bg-red-500 text-white`           |
| blue   | `bg-blue-500 text-white`          |
| yellow | `bg-yellow-500 text-gray-900`      |
| green  | `bg-green-500 text-white`         |

(Yellow uses dark text for contrast against the lighter background; the other three keep white text, matching the current red pill.)

## Scope

Files touched:
- Create: `frontend/src/utils/algorithmRunBadges.ts`
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx` (use shared util)
- Modify: `frontend/src/components/UnifiedNav.tsx` (use shared util, compute color, pass `badgeColor`)
- Modify: `frontend/src/components/NavSheet.tsx` (add `badgeColor` prop + class mapping)
- Tests: update/extend `ShiftsManagementPage.test.tsx`, `UnifiedNav.test.tsx`, and a new `algorithmRunBadges.test.ts`

No backend changes — there's no new "cancelled" status to introduce; the existing `error_message === "cancelled_by_user"` marker on `status === "failed"` jobs is sufficient to detect cancellation.

## Out of scope

- No change to how cancellation itself works server-side.
- No change to the "draft"/"done"/"failed" tab views inside `AlgorithmPage.tsx` (which already special-cases `error_message !== "cancelled_by_user"` for its own failed-jobs tab).
- No new badge colors beyond the 4 already defined.
