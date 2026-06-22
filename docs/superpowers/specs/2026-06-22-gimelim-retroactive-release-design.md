# Gimelim retroactive release + unified dismissal modal

## Problem

Today, releasing a primary soldier for medical reasons ("גימלים") and a regular
release ("שחרור") are two separate buttons and two separate modals
(`GimelimModal.tsx`, `DismissalModal.tsx`) on `ShiftDetailPanel`. The gimelim
flow always dismisses the *entire* shift — `from_date` is hardcoded to
`primary_a.start_date` — so there is no way to backdate when a gimelim release
actually took effect (e.g. recording today that a soldier should have been
released three days ago).

## Goals

- Allow picking the gimelim start day (`from_date`), defaulting to today,
  clamped to the shift's date range. The end of the dismissal stays locked to
  the end of the shift (unchanged behavior).
- Merge the regular dismiss and gimelim flows into one modal with a mode
  toggle, so there's a single entry point ("שחרור") instead of two buttons.

## Backend changes

### `backend/app/routes/gimelim.py`

`GimelimPreviewRequest` gains a required field:

```python
from_date: date
```

No default — the frontend always sends an explicit value.

### `backend/app/services/gimelim.py`

`preview_gimelim(...)` gains a `from_date: date` parameter.

- Validate `primary_a.start_date <= from_date <= primary_a.end_date - timedelta(days=1)`.
  Out-of-range raises `GimelimError("date_out_of_range")` → mapped to HTTP 400
  by the existing route exception handling.
- `from_date` is stored in the preview-token payload alongside the other
  snapshotted fields.
- `to_date` stays `primary_a.end_date - timedelta(days=1)` — unchanged. Gimelim
  always covers through the end of the shift; only the start is adjustable.

`commit_gimelim(...)`:

- Reads `from_date` back out of the payload and passes it (instead of
  `primary_a.start_date`) to `dismiss_primary(...)` and `call_up_reserve(...)`.
- No new staleness check is needed for `from_date` — it's a value supplied by
  the caller, not derived from mutable DB state, so it doesn't need the
  same "did this change since preview" guard as the other snapshotted IDs.

`rest_days` / future-slot search (`_find_future_slot`, `earliest_date`) are
unchanged — already anchored on `primary_a.end_date`, independent of
`from_date`.

## Frontend changes

### `frontend/src/components/DismissalModal.tsx` (merged; `GimelimModal.tsx` deleted)

New props:

```ts
interface Props {
  shift: CalendarShift;
  primary: CalendarShiftAssignee;
  canGimelim: boolean;        // gimelimEnabled && user is duty_manager/admin
  defaultRestDays: number;
  onClose: () => void;
  onDone: () => void;
}
```

New local state: `mode: "regular" | "gimelim"` (default `"regular"`).

- A segmented toggle ("רגיל" / "גימלים") renders at the top of the modal, only
  when `canGimelim` is true. When `canGimelim` is false, no toggle renders and
  the modal behaves exactly as today's `DismissalModal` (regular mode only).

**Regular mode** — unchanged from current `DismissalModal`: from/to day-grid
(both ends editable, defaults `[shift.start_date, shift.end_date]`), covering
reserve `Combobox`, optional reason input, single-step submit via
`dismissAndReallocate`.

**Gimelim mode**:

- Reuses the same day-grid component for date selection, with these
  differences:
  - `fromIdx` defaults to the index of today's date (clamped into
    `[shift.start_date, shift.end_date - 1 day]` if today falls outside the
    shift's range). Remains clickable to any day in that range — earlier or
    later than today, no additional restriction beyond the clamp.
  - `toIdx` is fixed at the last day of the shift and rendered as a
    non-interactive label (no click handler) instead of a clickable button.
  - Covering-reserve `Combobox` is hidden — gimelim always uses the linked
    reserve B, resolved server-side via `DutyReserveLink`.
  - Adds: rest-days number input (`defaultRestDays` initial value), mandatory
    reason textarea (validated non-empty on submit, mirroring current
    `GimelimModal` behavior), optional file upload (same accepted types/size
    limit as current `GimelimModal`: PDF/JPEG/PNG/GIF/WEBP, 20 MB max).
  - Submit is two-step, ported from current `GimelimModal`:
    1. "חשב הצעה" → calls `previewGimelim` (now also sending `from_date`) →
       shows the preview screen (current/future shift summary, warnings,
       token expiry countdown).
    2. "אשר ובצע" → calls `commitGimelim`, then fire-and-forget
       `uploadGimelimAttachment` if a file was selected.
  - "stale"/"expired" preview-token errors reset back to the form step, same
    as current `GimelimModal`.

### `frontend/src/api/gimelim.ts`

`previewGimelim` body type gains `from_date: string` (ISO date).

### `frontend/src/components/ShiftDetailPanel.tsx`

- Remove `gimelimTarget` state, the separate "גימלים 🏥" button, and the
  `GimelimModal` import/render block.
- The existing "שחרור" button for primary soldiers now opens the merged
  `DismissalModal`, passing `canGimelim={gimelimEnabled && (user?.role === "duty_manager" || user?.role === "admin")}`
  and `defaultRestDays={gimelimDefaultRestDays}`.
- `ReserveDismissalModal` (for reserve soldiers) is untouched — gimelim never
  applies to reserves.

### `frontend/src/i18n/he.json`

Add toggle labels under the existing `dismiss_modal` key, e.g.
`dismiss_modal.mode_regular` ("רגיל"), `dismiss_modal.mode_gimelim`
("גימלים"). Gimelim-specific strings inside the merged modal (rest-days
label, reason placeholder, file-upload hints, preview-step copy) stay as
inline Hebrew strings, matching the existing `GimelimModal` convention rather
than being newly externalized.

## Testing

- `backend/tests/unit/test_gimelim_service.py`: extend preview/commit tests
  with a backdated `from_date` (happy path — dismissal and call-up both start
  on the backdated day, `to_date` still equals shift end − 1) and an
  out-of-range `from_date` (before shift start, and on/after shift end →
  `GimelimError`).
- `backend/tests/integration/test_gimelim_api.py`: same coverage at the route
  level (400 for invalid `from_date`).
- Frontend: no existing dedicated test file for `GimelimModal`/`DismissalModal`
  found — none to update. (Re-check at implementation time in case one was
  added since this spec was written.)

## Out of scope

- No change to `rest_days`/future-slot reassignment logic.
- No change to the reserve dismissal flow (`ReserveDismissalModal`).
- No change to gimelim permission/visibility rules beyond folding the existing
  `gimelimEnabled && role` check into the `canGimelim` prop.
