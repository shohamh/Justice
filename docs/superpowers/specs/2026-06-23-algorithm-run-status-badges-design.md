# Algorithm Run Status Badges — Design

**Goal:** Show colored count badges next to the "ריצות אלגוריתם" section heading in [ShiftsManagementPage.tsx](../../../frontend/src/pages/planning/ShiftsManagementPage.tsx) so a planner can tell at a glance how many runs are in each state, without expanding the section.

## Scope

Only file touched: `frontend/src/pages/planning/ShiftsManagementPage.tsx`.

This is separate from the existing nav badge (`UnifiedNav.tsx`, added in a prior change) — that one shows a single aggregate count on the planning nav tab/sheet item and is untouched by this work.

## Groups & colors

Computed from `listJobs(50)` (`JobSummaryOut[]`, fields `status` and `mode`):

| Group     | Condition                                   | Color  |
|-----------|----------------------------------------------|--------|
| running   | `status === "pending"` or `"running"`        | blue   |
| draft     | `status === "done"` and `mode === "shadow"`  | yellow |
| done      | `status === "done"` and `mode === "dm_reviewed"` | green |
| failed    | `status === "failed"`                        | red    |

- A badge is rendered only when its count is `> 0`.
- Each badge shows just the count (a small colored pill), positioned inline in the heading row, before the existing expand/collapse arrow.
- Badge order left-to-right (visually, in RTL layout): running, draft, done, failed.

## Data fetching

- Add a `useEffect` in `ShiftsManagementPage` that calls `listJobs(50)` on mount.
- Store the raw `JobSummaryOut[]` (or the 4 derived counts) in component state.
- Derive the 4 counts from the fetched list on each fetch.
- Poll every 30s, but only while there is at least one job in `pending` or `running` status (mirrors the existing pattern in `UnifiedNav.tsx`'s badge effect — fetch once, then conditionally re-arm a `setInterval` only when active jobs exist, clearing it otherwise).
- Errors from the fetch are silently ignored (consistent with `UnifiedNav.tsx`'s existing badge fetch — a failed poll just leaves the last known counts in place).
- No need to pass `onJobSubmitted`-style refresh hook through child components; the page's own poll cadence (≤30s) is sufficient for badge freshness. The section can also be refetched once when `handleJobSubmitted` fires (i.e. right after a new job is submitted), to make the new `running` badge appear immediately rather than waiting for the next poll tick.

## UI placement

Inside the "Algorithm runs collapsible" `<section>` (around `ShiftsManagementPage.tsx:39-60`), in the heading `<button>` row that currently has:

```tsx
<h2 className="text-xl font-semibold">ריצות אלגוריתם</h2>
<span className="text-gray-400 ...">{runsOpen ? "▲" : "▼"}</span>
```

Insert a badge row between the `<h2>` and the arrow `<span>`: a `flex` container of up to 4 small pill `<span>` elements, each with a background/text color pair (e.g. blue-100/blue-800, yellow-100/yellow-800, green-100/green-800, red-100/red-800, with dark-mode variants), each showing just the numeric count. Pills are omitted entirely when their count is 0; if all counts are 0, no badge row renders.

## Out of scope

- No changes to `UnifiedNav.tsx` or its existing aggregate badge.
- No changes to backend, `listJobs` API, or `JobSummaryOut` shape.
- No tooltips/labels on the badges beyond the count (matches the "different colored badge" ask — color conveys the group).
