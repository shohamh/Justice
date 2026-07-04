# Upcoming-duties soldier modal: close-X + שחרור פיקודי shortcut
**Date:** 2026-07-04

---

## Overview

The soldier detail modal shown when clicking a badge in the commander dashboard's
"upcoming duties" widget (`UpcomingSnapshot.tsx`) currently has a bottom `ביטול`
button as its only way to close. This adds a proper close-X in the header (matching
the rest of the app's modal convention) and a new **שחרור פיקודי** ("commander
release") action that jumps straight into the existing הקפצה פיקודית (forced
call-up) flow for that specific soldier/assignment, since pulling someone from a
duty via this modal is exactly what that flow already does.

---

## 1. Modal close button (`UpcomingSnapshot.tsx`)

- Remove the bottom `ביטול` button.
- Add a header row: soldier name/link on one side, a `✕` close button on the
  other (end of the flex row — renders top-left under `dir="rtl"`).
- Match existing convention used elsewhere in the app (`DismissalModal.tsx`,
  `GenerateShiftsModal.tsx`, `ExemptionTypeViewModal.tsx`): `aria-label="סגור"`,
  `className="text-gray-400 hover:text-gray-600 text-xl leading-none"`.

## 2. שחרור פיקודי button

- New button in the modal, below the existing תורנות/יחידה details, styled as a
  rare/serious action (amber tone, consistent with other "handle with care"
  actions in this codebase — e.g. the `cancel` shift action uses
  `bg-amber-100 ... text-amber-800`).
- On click, uses `window.confirm` (the app's established confirmation pattern —
  no shared `ConfirmDialog` component exists) with a message that:
  1. names the soldier,
  2. states this triggers the הקפצה פיקודית mechanism,
  3. states it's for extreme cases only.

  Example text:
  > "פעולה זו תפעיל מנגנון הקפצה פיקודית עבור **{שם החייל}** — מיועד למקרים
  > קיצוניים בלבד (מחלה, צורך מבצעי דחוף). להמשיך?"

- On confirm: `useNavigate()` to
  `/commander/hakpaza?soldierId={selected.soldier_id}&assignmentId={selected.assignment_id}`.
- If `selected.soldier_id` is missing (assignment has no soldier attached),
  the button is disabled/hidden — nothing to pull.

## 3. HakpazaPage pre-fill (`HakpazaPage.tsx`)

`HakpazaPage` currently always starts at step 1 (soldier search). Add support
for arriving pre-filled:

- Read `soldierId` / `assignmentId` from `useSearchParams()` in a `useEffect`
  that runs once on mount (only when both params are present).
- Fetch the soldier via `getSoldier(soldierId)` and set as `pulledSoldier`.
- Fetch assignments via `listAssignments(soldierId, { date_from: today })`,
  filter to `status === "published"` (same filter `handleSoldierSelect` uses),
  and find the one matching `assignmentId`.
  - If found: set as `selectedAssignment`, set `pullDate` the same way
    `handleSoldierSelect`'s existing flow does (`start_date` if in the future,
    else `today`), and jump straight to **step 2** so the commander only needs
    to confirm/adjust the pull date and click "חפש מחליפים".
  - If not found (e.g. assignment was cancelled/changed since the modal was
    opened) or either fetch fails: fall back to step 1 with an inline error
    message ("לא נמצאה התורנות המבוקשת — בחר חייל ידנית"), soldier list still
    loads normally so the commander can proceed manually.
- This pre-fill effect only runs once; it doesn't interfere with the existing
  manual step-1 soldier search flow used when navigating to the page directly
  from the nav.

---

## Scope / non-goals

- No backend or API changes — `getSoldier` and `listAssignments` already exist
  and cover everything needed.
- No changes to the הקפצה פיקודית approval flow itself (steps 3–5 of
  `HakpazaPage`) — this only affects how step 1/2 can be pre-populated.
- No new shared `ConfirmDialog` component — follows the existing
  `window.confirm` convention used throughout `ShiftsPage.tsx` and elsewhere.

---

## Testing

- Clicking a badge in `UpcomingSnapshot` opens the modal; the `✕` closes it
  (bottom `ביטול` button is gone).
- Clicking שחרור פיקודי shows a `window.confirm` naming the soldier and
  mentioning "מקרים קיצוניים".
- Confirming navigates to `/commander/hakpaza?soldierId=...&assignmentId=...`.
- Landing on `HakpazaPage` with valid `soldierId`/`assignmentId` query params
  skips straight to step 2 with the correct soldier and assignment selected.
- Landing on `HakpazaPage` with an `assignmentId` that doesn't match any of the
  soldier's published assignments falls back to step 1 with an error message.
- Navigating to `/commander/hakpaza` with no query params behaves exactly as
  before (manual step-1 search).
