# Plan A — Homepage Dashboard Polish
**Date:** 2026-06-06  
**Issues:** #1, #2, #3, #4, #5, #7

---

## Overview

Improve the homepage dashboard so every element is actionable, informative, and visually correct. Add Israeli holidays to the calendar as reference events.

---

## 1. Calendar duty click (#1)

**Current state:** `DutyCalendarWidget` calls `eventClick={() => {}}` — no-op.

**Design:**
- Wire `eventClick` to open a modal wrapping the existing `ShiftDetailPanel` component.
- Pass the full `EffectiveDuty` object (already in the `duties` array via `event.id` → lookup) to the panel.
- Panel shows: duty type, location, date range, partner soldier names, reserve/primary status.
- Panel includes a "בקש החלפה" button that navigates to `/swaps?new=<assignment_id>` or opens `OfferSwapModal` inline.
- The modal is dismissible via backdrop click or Escape.

**Components changed:** `DutyCalendarWidget.tsx` (add `eventClick` handler + modal state), reuse `ShiftDetailPanel`.

---

## 2. Multi-week event hover highlight (#2)

**Current state:** FullCalendar renders a multi-week event as two separate DOM segments (one per week row). Hovering over the first segment doesn't highlight the second.

**Design:**
- Use `eventMouseEnter` and `eventMouseLeave` callbacks.
- On enter: find all DOM elements with `data-event-id="<id>"` (FullCalendar sets this) and add a `fc-event-hover` CSS class to all of them.
- On leave: remove the class from all of them.
- Add CSS: `.fc-event-hover { filter: brightness(0.85); }`.
- No FullCalendar internals are mutated; purely additive CSS.

---

## 3. Upcoming duties clickable (#3)

**Current state:** `UpcomingDutiesWidget` renders a plain table with no interactions.

**Design:**
- Each `<tr>` gains `cursor-pointer hover:bg-gray-50` and an `onClick` that opens the same duty detail modal as #1 (shared modal state lifted to the parent widget or passed via a callback prop from `HomePage`).
- Inside the modal: add "בקש החלפה" action button.
- The modal is the same component used in the calendar click, ensuring one implementation.

---

## 4. Swap status widget (#4)

**Current state:** Title is "החלפות שלי"; shows only date and status chip.

**Design:**
- Rename title to **"ההחלפות שלי"**.
- Add columns per swap row: duty type name, other party's full name (requester or acceptor), date range (`start_date – end_date` not just `duty_date`).
- The `SwapRequest` API type needs to expose `duty_type_id`, `other_party_name`, `start_date`, `end_date`. Verify what the existing `/swaps/my` endpoint returns; add fields if missing.
- Status chip labels extended to cover all statuses: `open`, `pending_approval`, `approved`, `rejected`.

---

## 5. Pending approvals — all categories (#5)

**Current state:** `PendingApprovalsWidget` only shows enrollment requests and incoming swap counts.

**Design:**
- Add three more rows matching what the nav badge already fetches:
  - "בקשות אישי ממתינות" (personal constraints) → link to `/approvals?tab=constraints`
  - "בקשות פטור ממתינות" (exemption requests) → link to `/approvals?tab=exemptions`
  - "עדכוני פרופיל ממתינים" (field updates) → link to `/approvals?tab=field-updates`
- Each row shows count chip (red) and a link.
- `PendingApprovalsWidget` props expanded to accept `pendingConstraints`, `pendingExemptions`, `pendingFieldUpdates` counts; `HomePage` fetches these (reuse the same API calls already used by `UnifiedNav`).
- Widget renders null only when ALL counts are zero.

---

## 6. Israeli holidays in calendar (#7)

**Backend:**
- Add `holidays` Python package (`pip install holidays`).
- New endpoint: `GET /calendar/holidays?year=YYYY` — returns `[{date: "YYYY-MM-DD", name: "שם החג"}]` for Israel.
- Uses `holidays.Israel(years=year)` (or `holidays.country_holidays("IL", years=year)`).
- No auth required (public reference data).

**Frontend:**
- `DutyCalendarWidget` fetches holidays for the currently visible year on mount and on month navigation.
- Holidays rendered as FullCalendar `background` events (type `"background"`) with a light gold/yellow color and the holiday name as title.
- They are not clickable (no `eventClick` handler fires for them — distinguished by a `type: "holiday"` property on the event object).

---

## Data / API changes

| Change | Type |
|--------|------|
| `GET /calendar/holidays?year=YYYY` | New endpoint |
| `SwapRequest` DTO: add `start_date`, `end_date`, `other_party_name`, `duty_type_id` | Extend existing |
| `PendingApprovalsWidget` props | Extended |

---

## Testing

- Click a calendar event → modal opens with correct duty details.
- Hover a multi-week event → both segments highlight simultaneously.
- Click an upcoming duty row → same modal opens.
- Swap widget shows correct other-party name and date range.
- Pending approvals widget shows all 5 categories when each has pending items.
- `/calendar/holidays?year=2026` returns Rosh Hashana, Yom Kippur, etc.
- Holidays appear in calendar as background events, not clickable.
