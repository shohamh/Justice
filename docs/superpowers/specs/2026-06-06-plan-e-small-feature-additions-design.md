# Plan E — Small Feature Additions
**Date:** 2026-06-06  
**Issues:** #11, #15, #26

---

## Overview

Three self-contained feature additions: indefinite exemptions, a "why did I get this duty?" button on individual duties, and swap eligibility validation in the offer modal.

---

## 1. Indefinite exemptions (#11)

**Current state:** The exemption grant form always requires an end date. The backend model (`SoldierExemption.end_date`) already accepts `null` (indefinite), so this is a frontend-only fix.

**Design:**
- In `ExemptionsPanel.tsx` (or wherever the grant form is rendered), add a checkbox: **"ללא הגבלת זמן (פטור קבוע)"**.
- When checked:
  - The end-date `<input type="date">` is disabled (greyed out) and its value cleared.
  - The form submits `end_date: null`.
- When unchecked: end-date is required as before.
- Display in the exemptions list: if `end_date` is null, show **"ללא הגבלה"** instead of a date.

**No backend changes needed.**

---

## 2. "למה קיבלתי?" button per duty (#15)

**Current state:** There is no per-duty explanation trigger in the UI. `ExplanationModal` exists but is not wired to individual duty rows.

**Design:**

**Where the button appears:**
- Each row in `UpcomingDutiesWidget` — a small `?` icon button at the end of the row.
- Each duty in the duty detail modal (opened from calendar click or upcoming duties click).
- In `DutyManagementPage`, for duty managers/commanders: each assigned soldier row has a `?` button.

**For commanders:**
- On the commander dashboard's soldier list, each assignment has a `?` button to see why that soldier received the duty.
- Scope: can only view explanations for soldiers in their sub-hierarchy.

**Flow:**
- Clicking `?` calls `GET /assignments/{assignment_id}/explanation` (already exists).
- Opens `ExplanationModal` (redesigned per Plan D #25).
- If no explanation data exists (e.g., manually assigned), show: **"תורנות זו שובצה ידנית — אין הסבר אלגוריתמי."**

**Authorization:** A soldier can only fetch their own assignment explanations. Commanders can fetch explanations for soldiers in their scope.

---

## 3. Swap eligibility validation (#26)

**Current state:** `OfferSwapModal` lists all duties without checking whether the offer recipient can actually accept them (due to eligibility or scheduling conflicts).

**Design:**

**Backend:**
- New endpoint: `GET /swaps/eligible-duties?target_soldier_id=<id>` — returns, for each of the current user's assignable duties, whether the target soldier is eligible to take it. Returns:
  ```json
  [
    {
      "assignment_id": "...",
      "eligible": false,
      "reason": "אילוץ אישי מאושר בתאריך זה"
    }
  ]
  ```
  Checks: active exemptions for the duty type, approved personal constraints overlapping the duty dates, density cap (too many duties in the rolling window), eligibility exclusions (mitvahim/alal).

**Frontend (`OfferSwapModal.tsx`):**
- When the modal opens with a target soldier selected, fetch the eligibility list.
- Ineligible duty rows are rendered with:
  - `opacity-50 cursor-not-allowed` Tailwind classes.
  - Disabled radio/checkbox.
  - On desktop: `title` attribute with the reason (shows on hover as native tooltip).
  - On mobile (touch device detection via `navigator.maxTouchPoints > 0`): tapping an ineligible row shows a non-dismissible toast notification with the reason for 3 seconds instead of selecting it.
- Eligible duties look and behave as before.
- A loading spinner shows while the eligibility check is in progress.

---

## Data / API changes

| Change | Type |
|--------|------|
| `GET /swaps/eligible-duties?target_soldier_id=` | New endpoint |
| `ExemptionsPanel` grant form: `end_date` optional | Frontend only |

---

## Testing

- Grant exemption with "indefinite" checkbox → `end_date` is null in DB, displayed as "ללא הגבלה".
- Upcoming duties rows show `?` button → explanation modal opens.
- Explanation modal shows "ידנית" message when no algorithm data exists.
- In OfferSwapModal, duty with scheduling conflict is greyed out and unselectable.
- Hovering greyed-out duty shows reason tooltip on desktop.
- Tapping greyed-out duty on mobile shows toast with reason.
